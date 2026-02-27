▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
 > Takeoff drone to 1m                                                                                    
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  get_action_details (ros-mcp-server MCP Server) {"action":"/drone_control/takeoff"}              │
│                                                                                                    │
│ {                                                                                                  │
│   "action": "/drone_control/takeoff",                                                              │
│   "action_type": "drone_interfaces/action/DroneTakeoff",                                           │
│   "goal": {                                                                                        │
│     "fields": {                                                                                    │
│       "target_altitude": "float"                                                                   │
│     },                                                                                             │
│     "field_count": 1,                                                                              │
│     "field_details": {                                                                             │
│       "target_altitude": {                                                                         │
│         "type": "float",                                                                           │
│         "array_length": -1,                                                                        │
│         "example": "0.0"                                                                           │
│       }                                                                                            │
│     },                                                                                             │
│     "message_type": "drone_interfaces/DroneTakeoff_Goal",                                          │
│     "examples": [                                                                                  │
│       "0.0"                                                                                        │
│     ],                                                                                             │
│     "constants": {                                                                                 │
│       "SLOT_TYPES": "(<rosidl_parser.definition.BasicType object at 0x7d52300d4100>,)",            │
│       "target_altitude": "0.0"                                                                     │
│     }                                                                                              │
│   },                                                                                               │
│   "result": {                                                                                      │
│     "fields": {                                                                                    │
│       "success": "boolean",                                                                        │
│       "message": "string"                                                                          │
│     },                                                                                             │
│     "field_count": 2,                                                                              │
│     "field_details": {                                                                             │
│       "success": {                                                                                 │
│         "type": "boolean",                                                                         │
│         "array_length": -1,                                                                        │
│         "example": "False"                                                                         │
│       },                                                                                           │
│       "message": {                                                                                 │
│         "type": "string",                                                                          │
│         "array_length": -1,                                                                        │
│         "example": ""                                                                              │
│       }                                                                                            │
│     },                                                                                             │
│     "message_type": "drone_interfaces/DroneTakeoff_Result",                                        │
│     "examples": [                                                                                  │
│       "False",                                                                                     │
│       ""                                                                                           │
│     ],                                                                                             │
│     "constants": {                                                                                 │
│       "SLOT_TYPES": "(<rosidl_parser.definition.BasicType object at 0x7d52300d5780>,               │
│ <rosidl_parser.definition.UnboundedString object at 0x7d52302b9fa0>)",                             │
│       "message": "",                                                                               │
│       "success": "False"                                                                           │
│     }                                                                                              │
│   },                                                                                               │
│   "feedback": {                                                                                    │
│     "fields": {                                                                                    │
│       "current_altitude": "float"                                                                  │
│     },                                                                                             │
│     "field_count": 1,                                                                              │
│     "field_details": {                                                                             │
│       "current_altitude": {                                                                        │
│         "type": "float",                                                                           │
│         "array_length": -1,                                                                        │
│         "example": "0.0"                                                                           │
│       }                                                                                            │
│     },                                                                                             │
│     "message_type": "drone_interfaces/DroneTakeoff_Feedback",                                      │
│     "examples": [                                                                                  │
│       "0.0"                                                                                        │
│     ],                                                                                             │
│     "constants": {                                                                                 │
│       "SLOT_TYPES": "(<rosidl_parser.definition.BasicType object at 0x7d52300d5900>,)",            │
│       "current_altitude": "0.0"                                                                    │
│     }                                                                                              │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  send_action_goal (ros-mcp-server MCP Server) {"timeout":60,"action_name":"/drone_control/takeo… │
│                                                                                                    │
│ {                                                                                                  │
│   "action": "/drone_control/takeoff",                                                              │
│   "action_type": "drone_interfaces/action/DroneTakeoff",                                           │
│   "success": true,                                                                                 │
│   "goal_id": "goal_1772164073916_98ddcaaa",                                                        │
│   "status": 6,                                                                                     │
│   "result": {                                                                                      │
│     "success": false,                                                                              │
│     "message": ""                                                                                  │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  subscribe_once (ros-mcp-server MCP Server) {"topic":"/mavros/state","msg_type":"mavros_msgs/ms… │
│                                                                                                    │
│ {                                                                                                  │
│   "msg": {                                                                                         │
│     "header": {                                                                                    │
│       "stamp": {                                                                                   │
│         "sec": 1772164068,                                                                         │
│         "nanosec": 212963393                                                                       │
│       },                                                                                           │
│       "frame_id": ""                                                                               │
│     },                                                                                             │
│     "connected": true,                                                                             │
│     "armed": false,                                                                                │
│     "guided": false,                                                                               │
│     "manual_input": true,                                                                          │
│     "mode": "POSCTL",                                                                              │
│     "system_status": 3                                                                             │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  call_service (ros-mcp-server MCP Server) {"service_type":"mavros_msgs/srv/CommandBool","servic… │
│                                                                                                    │
│ {                                                                                                  │
│   "service": "/mavros/cmd/arming",                                                                 │
│   "service_type": "mavros_msgs/srv/CommandBool",                                                   │
│   "success": true,                                                                                 │
│   "result": {                                                                                      │
│     "success": true,                                                                               │
│     "result": 0                                                                                    │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  send_action_goal (ros-mcp-server MCP Server) {"goal":{"target_altitude":1},"action_name":"/dro… │
│                                                                                                    │
│ {                                                                                                  │
│   "action": "/drone_control/takeoff",                                                              │
│   "action_type": "drone_interfaces/action/DroneTakeoff",                                           │
│   "success": true,                                                                                 │
│   "goal_id": "goal_1772164089242_79c6d389",                                                        │
│   "status": 6,                                                                                     │
│   "result": {                                                                                      │
│     "success": false,                                                                              │
│     "message": ""                                                                                  │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  call_service (ros-mcp-server MCP Server) {"service_type":"mavros_msgs/srv/SetMode","request":{… │
│                                                                                                    │
│ {                                                                                                  │
│   "service": "/mavros/set_mode",                                                                   │
│   "service_type": "mavros_msgs/srv/SetMode",                                                       │
│   "success": true,                                                                                 │
│   "result": {                                                                                      │
│     "mode_sent": true                                                                              │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  call_service (ros-mcp-server MCP Server) {"service_type":"mavros_msgs/srv/CommandBool","servic… │
│                                                                                                    │
│ {                                                                                                  │
│   "service": "/mavros/cmd/arming",                                                                 │
│   "service_type": "mavros_msgs/srv/CommandBool",                                                   │
│   "success": true,                                                                                 │
│   "result": {                                                                                      │
│     "success": true,                                                                               │
│     "result": 0                                                                                    │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  send_action_goal (ros-mcp-server MCP Server) {"timeout":60,"action_type":"drone_interfaces/act… │
│                                                                                                    │
│ {                                                                                                  │
│   "action": "/drone_control/takeoff",                                                              │
│   "action_type": "drone_interfaces/action/DroneTakeoff",                                           │
│   "success": true,                                                                                 │
│   "goal_id": "goal_1772164107153_1cbef170",                                                        │
│   "status": 6,                                                                                     │
│   "result": {                                                                                      │
│     "success": false,                                                                              │
│     "message": ""                                                                                  │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓  subscribe_once (ros-mcp-server MCP Server) {"msg_type":"geometry_msgs/msg/PoseStamped","topic"… │
│                                                                                                    │
│ {                                                                                                  │
│   "msg": {                                                                                         │
│     "header": {                                                                                    │
│       "stamp": {                                                                                   │
│         "sec": 1772164114,                                                                         │
│         "nanosec": 681798144                                                                       │
│       },                                                                                           │
│       "frame_id": "map"                                                                            │
│     },                                                                                             │
│     "pose": {                                                                                      │
│       "position": {                                                                                │
│         "x": -0.006092310883104801,                                                                │
│         "y": 0.03775200620293617,                                                                  │
│         "z": 0.025268271565437317                                                                  │
│       },                                                                                           │
│       "orientation": {                                                                             │
│         "x": -0.00017170247420240375,                                                              │
│         "y": -0.0012665193831973877,                                                               │
│         "z": 0.05803115277767984,                                                                  │
│         "w": -0.9983140246515961                                                                   │
│       }                                                                                            │
│     }                                                                                              │
│   }                                                                                                │
│ }                                                                                                  │
╰────────────────────────────────────────────────────────────────────────────────────────────────────╯

ℹ Request cancelled.
