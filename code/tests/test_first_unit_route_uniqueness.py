"""The integrated Mac app must expose only the operator-owned body pose route.

A standalone router test cannot detect another route registered first by
create_app. Starlette dispatches to the first matching path and method, so a
new tool-authorized pose route can silently shadow the protected diagnostic.
"""

from desk_robot.api import create_app


def test_first_unit_pose_route_is_unique_and_operator_only(settings):
    app = create_app(settings)
    pose_routes = [
        route for route in app.routes
        if getattr(route, "path", None) == "/v1/robots/{robot_id}/pose"
        and "GET" in getattr(route, "methods", ())
    ]
    assert len(pose_routes) == 1, (
        "Duplicate body pose routes shadow operator authorization and legacy "
        "firmware responses"
    )
    assert any(
        getattr(dependency.call, "__name__", None) == "operator"
        for dependency in pose_routes[0].dependant.dependencies
    ), "The body pose diagnostic must require operator authorization"
