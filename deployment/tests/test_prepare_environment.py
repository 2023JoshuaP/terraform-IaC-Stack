import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "prepare_environment", Path(__file__).resolve().parents[1] / "prepare-environment.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EnvironmentTests(unittest.TestCase):
    def test_trust_requires_expected_service_and_action(self):
        role = {"AssumeRolePolicyDocument": {"Statement": [{
            "Effect": "Allow", "Principal": {"Service": ["ec2.amazonaws.com"]},
            "Action": "sts:AssumeRole"}]}}
        self.assertTrue(module.trusts(role, "ec2.amazonaws.com"))
        self.assertFalse(module.trusts(role, "eks.amazonaws.com"))

    def test_select_unique_checked_role_only(self):
        roles = [{"name": "A", "arn": "arn:A", "status": "allowed"}]
        self.assertEqual(module.choose(roles, None, False), "arn:A")
        with self.assertRaises(ValueError):
            module.choose(roles * 2, None, False)

    def test_excludes_aws_service_linked_roles(self):
        role = {"Arn": "arn:aws:iam::123456789012:role/aws-service-role/eks.amazonaws.com/AWSServiceRoleForAmazonEKS",
                "AssumeRolePolicyDocument": {"Statement": [{"Effect": "Allow",
                    "Principal": {"Service": "eks.amazonaws.com"}, "Action": "sts:AssumeRole"}]}}
        self.assertFalse(module.trusts(role, "eks.amazonaws.com"))

    def test_unknown_requires_explicit_choice_and_acknowledgement(self):
        roles = [{"name": "A", "arn": "arn:A", "status": "unknown"}]
        for requested, acknowledge in ((None, True), ("A", False)):
            with self.assertRaises(ValueError):
                module.choose(roles, requested, acknowledge)
        self.assertEqual(module.choose(roles, "A", True), "arn:A")
        roles[0]["status"] = "denied"
        with self.assertRaises(ValueError):
            module.choose(roles, "A", True)

    def test_assignment_preserves_comments_and_requires_key(self):
        self.assertEqual(module.assignment('create_iam_roles = true # lab\n',
                                          'create_iam_roles', False),
                         'create_iam_roles = false # lab\n')
        with self.assertRaises(ValueError):
            module.assignment('other = true\n', 'create_iam_roles', False)

    def test_unavailable_simulation_is_not_success(self):
        with patch.object(module, "aws", side_effect=ValueError("AccessDenied")):
            result = module.permissions({"Arn": "arn:A"}, "node", "aws", "123456789012", "us-east-1", "lab")
        self.assertTrue(all(r['status'] == 'unknown' for r in result))

    def test_resource_denial_is_detected(self):
        response = {"EvaluationResults": [{"EvalActionName": "ecr:PutImage", "EvalDecision": "allowed",
            "ResourceSpecificResults": [{"EvalResourceDecision": "explicitDeny"}]}]}
        with patch.object(module, "aws", return_value=response):
            result = module.permissions({"Arn": "arn:A"}, "node", "aws", "123456789012", "us-east-1", "lab")
        self.assertTrue(all(r['status'] == 'denied' for r in result))

    def test_cross_account_and_role_replacement_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "ROOT", Path(directory)):
            p = Path(directory) / 'stacks/network/terraform.tfstate'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'resources': [{'type': 'aws_eks_cluster', 'instances': [
                {'attributes': {'arn': 'arn:aws:eks:us-east-1:123456789012:cluster/lab',
                                'role_arn': 'arn:aws:iam::123456789012:role/Old'}}]}]}))
            with self.assertRaises(ValueError):
                module.guard_states('999999999999')
            with self.assertRaises(ValueError):
                module.guard_states('123456789012', 'arn:aws:iam::123456789012:role/New')
            module.guard_states('123456789012', 'arn:aws:iam::123456789012:role/Old')


if __name__ == '__main__':
    unittest.main()
