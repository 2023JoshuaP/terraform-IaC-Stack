import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "deploy_all", Path(__file__).resolve().parents[1] / "deploy-all.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def args():
    return argparse.Namespace(region="us-east-1", cluster_role="Cluster", node_role="Node",
                              yes=True, rebuild=False, ready_timeout=900)


class DeploymentTests(unittest.TestCase):
    def test_rejects_deletes_and_replacements(self):
        for actions in (["delete"], ["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                module.safe_plan({"resource_changes": [{"address": "example", "change": {"actions": actions}}]})
        module.safe_plan({"resource_changes": [{"address": "example", "change": {"actions": ["create"]}}]})

    def test_ready_count_excludes_unready_and_cordoned(self):
        ready = {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}
        cordoned = {**ready, "spec": {"unschedulable": True}}
        self.assertFalse(module.nodes_ready([ready, cordoned, {}], 2))
        self.assertTrue(module.nodes_ready([ready, ready], 2))

    def test_image_metadata_must_match_exact_repository(self):
        self.assertTrue(module.image_matches({"image": "registry/repo:v1"}, "registry/repo"))
        for image in ("registry/repo-other:v1", "other/repo:v1", "registry/repo:"):
            self.assertFalse(module.image_matches({"image": image}, "registry/repo"))

    def test_wait_retries_until_ready(self):
        with patch.object(module.time, "sleep") as sleep:
            checks = iter([False, True])
            module.wait_until("test", lambda: next(checks), 100)
        sleep.assert_called_once()

    def test_wait_has_deadline(self):
        with patch.object(module.time, "monotonic", side_effect=[0, 2]), self.assertRaises(ValueError):
            module.wait_until("test", lambda: False, 1)

    def test_terraform_never_applies_destructive_plan(self):
        plan = {"resource_changes": [{"address": "example", "change": {"actions": ["delete"]}}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "run", return_value=json.dumps(plan)) as run:
            deploy = module.Deployment(args(), Path(directory))
            with self.assertRaises(ValueError):
                deploy.terraform("network")
            self.assertFalse(any("apply" in c.args[0] for c in run.call_args_list))

    def test_terraform_failure_stops_before_apply(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "run", side_effect=subprocess.CalledProcessError(1, "terraform")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                module.Deployment(args(), Path(directory)).terraform("network")
            self.assertEqual(run.call_count, 1)

    def test_full_sequence_without_aws(self):
        host = "test.us-east-1.elb.amazonaws.com"
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            return ""

        def kubectl(*command, **kwargs):
            commands.append(list(command))
            if "nodes" in command:
                return json.dumps({"items": [{"status": {"conditions": [{"type": "Ready", "status": "True"}]}}] * 2})
            if "get" in command and "ingress" in command:
                return host
            return ""

        def aws(*command):
            if command[0] == "sts":
                return {"Account": "123456789012"}
            return {"nodegroup": {"scalingConfig": {"desiredSize": 2}}}

        with tempfile.TemporaryDirectory() as directory, patch.object(module, "run", side_effect=run), \
                patch.object(module, "aws_json", side_effect=aws), \
                patch.object(module, "tf_outputs", return_value={"cluster_name": "test-cluster"}), \
                patch.object(module.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            deploy = module.Deployment(args(), Path(directory))
            deploy.kubectl = kubectl
            deploy.terraform = lambda stack: commands.append(["terraform-stage", stack])
            deploy.build = lambda component: commands.append(["build-stage", component])
            deploy.execute()
            self.assertEqual([c[1] for c in commands if c[0] == "terraform-stage"],
                             ["backend", "frontend", "network", "database"])
            self.assertEqual([c[1] for c in commands if c[0] == "build-stage"], ["backend", "frontend"])
            app_commands = [c for c in commands if len(c) > 1 and c[1] == "deployment/deploy-apps.py"]
            self.assertEqual(app_commands[0][-1], "http://localhost")
            self.assertEqual(app_commands[1][-1], "http://" + host)
            self.assertEqual(json.loads((Path(directory) / "result.json").read_text())["smoke_test"], "passed")


if __name__ == "__main__":
    unittest.main()
