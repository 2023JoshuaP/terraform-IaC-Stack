#!/usr/bin/env python3
"""Prueba frontend y API desde Internet; crea solo un usuario sintético de prueba."""
import argparse
from http.cookiejar import CookieJar
import json
import secrets
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Origen del ALB, por ejemplo http://host.elb.amazonaws.com")
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def request(path, expected=200, method="GET", body=None):
        headers = {"Origin": origin}
        if method != "GET":
            token = json.loads(request("/api/users/csrf"))["token"]
            headers.update({"Content-Type": "application/json", "X-XSRF-TOKEN": token})
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(origin + path, data=data, method=method, headers=headers)
        with opener.open(req, timeout=30) as response:
            assert response.status == expected, f"{method} {path}: HTTP {response.status}, esperado {expected}"
            value = response.read()
        print(f"OK {method} {path} → {expected}")
        return value

    try:
        homepage = request("/")
        assert b"<html" in homepage.lower(), "El frontend no devuelve HTML"
        scholarships = json.loads(request("/api/scholarships/get_all"))
        assert isinstance(scholarships, list), "La API de becas no devuelve una lista"
        username = "cloudtest" + secrets.token_hex(4)
        password = secrets.token_hex(16)
        request("/api/users/register", 201, "POST", {
            "username": username, "email": f"{username}@example.invalid", "password": password
        })
        request("/api/users/login", 200, "POST", {"username": username, "password": password})
        user = json.loads(request("/api/users/verifyToken"))
        assert user["username"] == username, "La sesión no corresponde al usuario de prueba"
        request("/api/users/logout", 204, "POST")
        print("Frontend, PostgreSQL, registro, login, cookie JWT y logout verificados con datos sintéticos.")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Fallo HTTP {error.code} en {error.url}; revisar logs de la aplicación.") from None


if __name__ == "__main__":
    main()
