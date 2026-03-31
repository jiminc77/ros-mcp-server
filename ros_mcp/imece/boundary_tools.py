"""IMECE-filtered generic tool registrations."""

from __future__ import annotations

import json
import time
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.websocket import WebSocketManager

from .constants import ALLOWED_SERVICES, ALLOWED_TOPIC_TYPES


def _rosapi_call(ws_manager: WebSocketManager, service: str, args: dict[str, Any]) -> dict[str, Any]:
    with ws_manager:
        return ws_manager.request(
            {
                "op": "call_service",
                "service": service,
                "args": args,
                "id": f"imece_{service.replace('/', '_')}",
            }
        )


def _allowed_topic(topic: str, msg_type: str | None = None, *, publish: bool = False) -> str | None:
    expected = ALLOWED_TOPIC_TYPES.get(topic)
    if expected is None:
        return f"Topic {topic} is outside the IMECE local-pose control surface"
    if publish and topic != "/mavros/setpoint_position/local":
        return f"Publishing is only allowed on /mavros/setpoint_position/local, not {topic}"
    if msg_type and msg_type != expected:
        return f"Topic {topic} expects message type {expected}, not {msg_type}"
    return None


def _allowed_service(service: str, service_type: str | None = None) -> str | None:
    expected = ALLOWED_SERVICES.get(service)
    if expected is None:
        return f"Service {service} is outside the IMECE mode/arming control surface"
    if service_type and service_type != expected:
        return f"Service {service} expects type {expected}, not {service_type}"
    return None


def register_filtered_topic_tools(mcp: FastMCP, ws_manager: WebSocketManager) -> None:
    @mcp.tool(
        description="Get the IMECE-approved ROS topics for local-pose control and state observation.",
        annotations=ToolAnnotations(title="Get Topics", readOnlyHint=True),
    )
    def get_topics(wait_for_previous: bool | None = None) -> dict:
        del wait_for_previous
        response = _rosapi_call(ws_manager, "/rosapi/topics", {})
        values = response.get("values", {}) if isinstance(response, dict) else {}
        topics = values.get("topics", [])
        types = values.get("types", [])
        filtered_topics = []
        filtered_types = []
        for topic, msg_type in zip(topics, types):
            if topic in ALLOWED_TOPIC_TYPES and ALLOWED_TOPIC_TYPES[topic] == msg_type:
                filtered_topics.append(topic)
                filtered_types.append(msg_type)
        return {"topics": filtered_topics, "types": filtered_types, "topic_count": len(filtered_topics)}

    @mcp.tool(
        description="Get the type for an IMECE-approved ROS topic.",
        annotations=ToolAnnotations(title="Get Topic Type", readOnlyHint=True),
    )
    def get_topic_type(topic: str, wait_for_previous: bool | None = None) -> dict:
        del wait_for_previous
        error = _allowed_topic(topic)
        if error:
            return {"error": error}
        return {"topic": topic, "type": ALLOWED_TOPIC_TYPES[topic]}

    @mcp.tool(
        description="Get details for an IMECE-approved ROS topic.",
        annotations=ToolAnnotations(title="Get Topic Details", readOnlyHint=True),
    )
    def get_topic_details(topic: str, wait_for_previous: bool | None = None) -> dict:
        del wait_for_previous
        error = _allowed_topic(topic)
        if error:
            return {"error": error}

        publishers = _rosapi_call(ws_manager, "/rosapi/publishers", {"topic": topic}).get("values", {})
        subscribers = _rosapi_call(ws_manager, "/rosapi/subscribers", {"topic": topic}).get("values", {})
        return {
            "topic": topic,
            "type": ALLOWED_TOPIC_TYPES[topic],
            "publishers": publishers.get("publishers", []),
            "publisher_count": len(publishers.get("publishers", [])),
            "subscribers": subscribers.get("subscribers", []),
            "subscriber_count": len(subscribers.get("subscribers", [])),
        }

    @mcp.tool(
        description="Get the structure for an IMECE-approved message type.",
        annotations=ToolAnnotations(title="Get Message Details", readOnlyHint=True),
    )
    def get_message_details(
        message_type: str,
        wait_for_previous: bool | None = None,
    ) -> dict:
        del wait_for_previous
        if message_type not in set(ALLOWED_TOPIC_TYPES.values()):
            return {"error": f"Message type {message_type} is outside the IMECE control surface"}
        response = _rosapi_call(ws_manager, "/rosapi/message_details", {"type": message_type})
        values = response.get("values", {}) if isinstance(response, dict) else {}
        typedefs = values.get("typedefs", [])
        structure = {}
        for typedef in typedefs:
            type_name = typedef.get("type", message_type)
            structure[type_name] = {
                "fields": dict(zip(typedef.get("fieldnames", []), typedef.get("fieldtypes", []))),
                "field_count": len(typedef.get("fieldnames", [])),
            }
        return {"message_type": message_type, "structure": structure}

    @mcp.tool(
        description="Subscribe once to an IMECE-approved topic and return the first message.",
        annotations=ToolAnnotations(title="Subscribe Once", readOnlyHint=True),
    )
    def subscribe_once(
        topic: str = "",
        msg_type: str = "",
        timeout: float = 5.0,
        queue_length: int = 1,
        throttle_rate_ms: int = 0,
        wait_for_previous: bool | None = None,
    ) -> dict:
        del wait_for_previous
        error = _allowed_topic(topic, msg_type)
        if error:
            return {"error": error}

        subscribe_msg = {
            "op": "subscribe",
            "topic": topic,
            "type": msg_type,
            "queue_length": int(queue_length),
            "throttle_rate": int(throttle_rate_ms),
        }

        with ws_manager:
            send_error = ws_manager.send(subscribe_msg)
            if send_error:
                return {"error": send_error}

            end_time = time.time() + float(timeout)
            while time.time() < end_time:
                response = ws_manager.receive(timeout=0.5)
                if response is None:
                    continue
                message = json.loads(response)
                if message.get("op") == "publish" and message.get("topic") == topic:
                    ws_manager.send({"op": "unsubscribe", "topic": topic})
                    return {"msg": message.get("msg", {})}
                if message.get("op") == "status" and message.get("level") == "error":
                    ws_manager.send({"op": "unsubscribe", "topic": topic})
                    return {"error": message.get("msg", "Unknown rosbridge error")}

            ws_manager.send({"op": "unsubscribe", "topic": topic})
            return {"error": "Timeout waiting for message from topic"}

    @mcp.tool(
        description="Subscribe to an IMECE-approved topic for a fixed duration and collect messages.",
        annotations=ToolAnnotations(title="Subscribe for Duration", readOnlyHint=True),
    )
    def subscribe_for_duration(
        topic: str = "",
        msg_type: str = "",
        duration: float = 5.0,
        max_messages: int = 100,
        queue_length: int = 1,
        throttle_rate_ms: int = 0,
        wait_for_previous: bool | None = None,
    ) -> dict:
        del wait_for_previous
        error = _allowed_topic(topic, msg_type)
        if error:
            return {"error": error}

        subscribe_msg = {
            "op": "subscribe",
            "topic": topic,
            "type": msg_type,
            "queue_length": int(queue_length),
            "throttle_rate": int(throttle_rate_ms),
        }

        with ws_manager:
            send_error = ws_manager.send(subscribe_msg)
            if send_error:
                return {"error": send_error}

            collected = []
            end_time = time.time() + float(duration)
            while time.time() < end_time and len(collected) < int(max_messages):
                response = ws_manager.receive(timeout=0.5)
                if response is None:
                    continue
                message = json.loads(response)
                if message.get("op") == "publish" and message.get("topic") == topic:
                    collected.append(message.get("msg", {}))
                elif message.get("op") == "status" and message.get("level") == "error":
                    ws_manager.send({"op": "unsubscribe", "topic": topic})
                    return {"error": message.get("msg", "Unknown rosbridge error")}

            ws_manager.send({"op": "unsubscribe", "topic": topic})
            return {"topic": topic, "collected_count": len(collected), "messages": collected}

    @mcp.tool(
        description="Publish a single PoseStamped setpoint on /mavros/setpoint_position/local.",
        annotations=ToolAnnotations(title="Publish Once", destructiveHint=True),
    )
    def publish_once(
        topic: str = "",
        msg_type: str = "",
        msg: dict = {},
        wait_for_previous: bool | None = None,
    ) -> dict:
        del wait_for_previous
        error = _allowed_topic(topic, msg_type, publish=True)
        if error:
            return {"error": error}
        if not msg:
            return {"error": "msg cannot be empty"}

        with ws_manager:
            advertise_error = ws_manager.send({"op": "advertise", "topic": topic, "type": msg_type})
            if advertise_error:
                return {"error": advertise_error}
            publish_error = ws_manager.send({"op": "publish", "topic": topic, "msg": msg})
            ws_manager.send({"op": "unadvertise", "topic": topic})
        if publish_error:
            return {"error": publish_error}
        return {"success": True}

    @mcp.tool(
        description="Publish a sequence of PoseStamped setpoints on /mavros/setpoint_position/local.",
        annotations=ToolAnnotations(title="Publish for Durations", destructiveHint=True),
    )
    def publish_for_durations(
        topic: str = "",
        msg_type: str = "",
        messages: list[dict] = [],
        durations: list[float] = [],
        wait_for_previous: bool | None = None,
    ) -> dict:
        del wait_for_previous
        error = _allowed_topic(topic, msg_type, publish=True)
        if error:
            return {"error": error}
        if len(messages) != len(durations):
            return {"error": "messages and durations must have the same length"}

        published_count = 0
        with ws_manager:
            advertise_error = ws_manager.send({"op": "advertise", "topic": topic, "type": msg_type})
            if advertise_error:
                return {"error": advertise_error}
            for msg, delay in zip(messages, durations):
                publish_error = ws_manager.send({"op": "publish", "topic": topic, "msg": msg})
                if publish_error:
                    ws_manager.send({"op": "unadvertise", "topic": topic})
                    return {"error": publish_error}
                published_count += 1
                if delay:
                    time.sleep(float(delay))
            ws_manager.send({"op": "unadvertise", "topic": topic})
        return {"success": True, "published_count": published_count, "topic": topic, "msg_type": msg_type}


def register_filtered_service_tools(mcp: FastMCP, ws_manager: WebSocketManager) -> None:
    @mcp.tool(
        description="Get the IMECE-approved ROS services for mode and arming control.",
        annotations=ToolAnnotations(title="Get Services", readOnlyHint=True),
    )
    def get_services(wait_for_previous: bool | None = None) -> dict:
        del wait_for_previous
        response = _rosapi_call(ws_manager, "/rosapi/services", {})
        values = response.get("values", {}) if isinstance(response, dict) else {}
        services = [service for service in values.get("services", []) if service in ALLOWED_SERVICES]
        return {"services": services, "service_count": len(services)}

    @mcp.tool(
        description="Get the type for an IMECE-approved ROS service.",
        annotations=ToolAnnotations(title="Get Service Type", readOnlyHint=True),
    )
    def get_service_type(service: str, wait_for_previous: bool | None = None) -> dict:
        del wait_for_previous
        error = _allowed_service(service)
        if error:
            return {"error": error}
        return {"service": service, "type": ALLOWED_SERVICES[service]}

    @mcp.tool(
        description="Get details for an IMECE-approved ROS service.",
        annotations=ToolAnnotations(title="Get Service Details", readOnlyHint=True),
    )
    def get_service_details(service: str, wait_for_previous: bool | None = None) -> dict:
        del wait_for_previous
        error = _allowed_service(service)
        if error:
            return {"error": error}
        service_type = ALLOWED_SERVICES[service]
        request_details = _rosapi_call(
            ws_manager,
            "/rosapi/service_request_details",
            {"type": service_type},
        ).get("values", {})
        response_details = _rosapi_call(
            ws_manager,
            "/rosapi/service_response_details",
            {"type": service_type},
        ).get("values", {})
        providers = _rosapi_call(ws_manager, "/rosapi/service_node", {"service": service}).get("values", {})

        def _fields(details: dict[str, Any]) -> dict[str, Any]:
            typedefs = details.get("typedefs", [])
            if not typedefs:
                return {"fields": {}, "field_count": 0}
            typedef = typedefs[0]
            return {
                "fields": dict(zip(typedef.get("fieldnames", []), typedef.get("fieldtypes", []))),
                "field_count": len(typedef.get("fieldnames", [])),
            }

        return {
            "service": service,
            "type": service_type,
            "request": _fields(request_details),
            "response": _fields(response_details),
            "providers": [providers.get("node")] if providers.get("node") else [],
            "provider_count": 1 if providers.get("node") else 0,
            "note": "Only IMECE-approved mode/arming services are exposed.",
        }

    @mcp.tool(
        description="Call an IMECE-approved mode or arming ROS service.",
        annotations=ToolAnnotations(title="Call Service", destructiveHint=True),
    )
    def call_service(
        service_name: str,
        service_type: str,
        request: dict,
        timeout: float = 5.0,
        wait_for_previous: bool | None = None,
    ) -> dict:
        del wait_for_previous
        error = _allowed_service(service_name, service_type)
        if error:
            return {"error": error}
        with ws_manager:
            return ws_manager.request(
                {
                    "op": "call_service",
                    "service": service_name,
                    "type": service_type,
                    "args": request,
                    "id": f"imece_call_{service_name.replace('/', '_')}",
                },
                timeout=float(timeout),
            )
