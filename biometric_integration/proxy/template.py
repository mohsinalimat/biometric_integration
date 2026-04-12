# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""Nginx server block template generator."""

from __future__ import annotations


def get_server_block(site: str, port: int, gunicorn_port: int = 8000) -> str:
    """Generate the nginx server block for the biometric HTTP listener.

    Key design notes:
    - No X-Original-Request-URI header (page_renderer reads request.path directly)
    - underscores_in_headers on: accepts EBKN's underscore-style headers from devices
    - Underscore→dash header conversion: gunicorn/WSGI drops underscore headers,
      so nginx converts them to dash format (request_code → request-code) before
      proxying. The EBKN adapter's _get_header() tries both variants.
    """
    from frappe.utils import get_url
    try:
        site_url = get_url()
        hostname = site_url.split("//")[-1].split("/")[0].split(":")[0]
    except Exception:
        hostname = site

    return f"""# Biometric Integration — HTTP listener for {site} on port {port}
# Auto-generated — do not edit manually. Use Attendance Integration Settings to manage.
server {{
    listen {port};
    server_name _;

    # Required for EBKN: allows request_code, dev_id, blk_no, trans_id, cmd_return_code headers
    underscores_in_headers on;

    location / {{
        proxy_pass http://127.0.0.1:{gunicorn_port};
        proxy_set_header Host {hostname};
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto http;

        # EBKN sends underscore headers (request_code, dev_id, etc.) which
        # gunicorn/WSGI silently drops. Convert to dash format here so they
        # survive through to Werkzeug where the EBKN adapter reads them.
        proxy_set_header request-code $http_request_code;
        proxy_set_header dev-id $http_dev_id;
        proxy_set_header blk-no $http_blk_no;
        proxy_set_header trans-id $http_trans_id;
        proxy_set_header cmd-return-code $http_cmd_return_code;

        proxy_pass_request_headers on;
        proxy_read_timeout 60;
        proxy_connect_timeout 10;
    }}
}}
"""
