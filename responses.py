"""
Centralised API response helpers.

All JSON responses across every Blueprint go through these helpers so the
envelope shape is consistent and can be changed in one place.

Success envelope  →  {"success": true,  "data": {...}}
Error envelope    →  {"success": false, "error": {"code": "...", "message": "..."}}
"""

from http import HTTPStatus
from flask import jsonify
from typing import Any


def success(data: Any = None, status: int = HTTPStatus.OK):
    """Return a 2xx JSON response."""
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    return jsonify(payload), status


def created(data: Any = None):
    """Return a 201 Created JSON response."""
    return success(data, status=HTTPStatus.CREATED)


def error(
    message: str,
    code: str = "ERROR",
    status: int = HTTPStatus.BAD_REQUEST,
):
    """Return a 4xx/5xx JSON response."""
    return (
        jsonify(
            {
                "success": False,
                "error": {
                    "code": code,
                    "message": message,
                },
            }
        ),
        status,
    )


def not_found(resource: str = "Resource"):
    return error(
        f"{resource} not found.",
        code="NOT_FOUND",
        status=HTTPStatus.NOT_FOUND,
    )


def bad_request(message: str):
    return error(message, code="BAD_REQUEST", status=HTTPStatus.BAD_REQUEST)


def server_error(message: str = "An unexpected error occurred."):
    return error(
        message,
        code="INTERNAL_ERROR",
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


def service_unavailable(message: str):
    return error(
        message,
        code="SERVICE_UNAVAILABLE",
        status=HTTPStatus.SERVICE_UNAVAILABLE,
    )