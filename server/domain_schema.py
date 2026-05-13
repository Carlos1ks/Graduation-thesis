"""煤矿应急领域轻量 schema 定义。"""

HAZARD_DEFINITIONS = {
    "gas": {
        "label": "瓦斯灾害",
        "keywords": ["瓦斯", "超限", "积聚", "爆炸", "通风异常"],
    },
    "fire": {
        "label": "火灾灾害",
        "keywords": ["火灾", "明火", "火源", "烟雾", "高温", "燃烧"],
    },
    "water": {
        "label": "水害风险",
        "keywords": ["突水", "透水", "积水", "涌水", "淋水", "水位"],
    },
    "roof": {
        "label": "顶板风险",
        "keywords": ["冒顶", "顶板", "片帮", "离层", "垮落"],
    },
    "personnel": {
        "label": "人员风险",
        "keywords": ["被困", "失联", "中毒", "窒息", "伤亡", "撤离"],
    },
}

SYMPTOM_DEFINITIONS = {
    "smoke": {"label": "烟雾", "keywords": ["烟雾", "烟气", "浓烟"]},
    "gas_overlimit": {"label": "瓦斯超限", "keywords": ["瓦斯浓度", "超限", "浓度达到", "浓度持续上升"]},
    "water_inrush": {"label": "突水征兆", "keywords": ["涌水", "挂红", "挂汗", "底鼓", "淋水增大"]},
    "power_issue": {"label": "电气异常", "keywords": ["断电", "电源", "设备异常", "停电"]},
    "trapped": {"label": "人员被困", "keywords": ["被困", "失联", "通信中断"]},
}

ACTION_DEFINITIONS = {
    "stop_work": {"label": "停止作业", "keywords": ["停止作业", "停产", "停掘", "停止施工"]},
    "cut_power": {"label": "切断电源", "keywords": ["切断电源", "断电", "停电", "切电"]},
    "evacuate": {"label": "撤离人员", "keywords": ["撤人", "撤离", "疏散", "沿避灾路线"]},
    "ventilate": {"label": "加强通风", "keywords": ["通风", "稀释", "排放", "局部通风机"]},
    "alert": {"label": "设置警戒", "keywords": ["警戒", "封控", "禁止进入", "栅栏"]},
    "report": {"label": "上报调度", "keywords": ["调度室", "上报", "汇报", "报告"]},
    "rescue": {"label": "组织救援", "keywords": ["救援", "搜救", "救护队", "救护"]},
}

DEPARTMENT_DEFINITIONS = {
    "dispatch": {"label": "调度室", "keywords": ["调度室", "调度", "指挥中心"]},
    "ventilation": {"label": "通防部门", "keywords": ["通防", "通风队", "瓦斯检查员", "瓦斯抽采队"]},
    "electrical": {"label": "机电部门", "keywords": ["机电", "供电", "电工"]},
    "mining": {"label": "采掘班组", "keywords": ["采掘", "班组长", "现场班组", "掘进工作面"]},
    "safety": {"label": "安监部门", "keywords": ["安监", "安全管理", "安全员"]},
    "rescue_team": {"label": "矿山救护队", "keywords": ["救护队", "救援队", "专业救援"]},
}

LOCATION_DEFINITIONS = {
    "heading_face": {"label": "掘进工作面", "keywords": ["掘进工作面", "工作面"]},
    "return_airway": {"label": "回风巷", "keywords": ["回风巷", "回风"]},
    "fresh_air": {"label": "新鲜风流巷道", "keywords": ["新鲜风流", "进风巷", "避灾路线"]},
    "transport_roadway": {"label": "运输巷道", "keywords": ["运输巷道", "运输巷"]},
}

EQUIPMENT_DEFINITIONS = {
    "fan": {"label": "局部通风机", "keywords": ["局部通风机", "风机"]},
    "detector": {"label": "检测仪", "keywords": ["检测仪", "传感器", "监测"]},
    "communication": {"label": "通信设备", "keywords": ["对讲机", "广播", "通信终端"]},
}

PARAMETER_DEFINITIONS = {
    "gas_concentration": {"label": "瓦斯浓度", "keywords": ["瓦斯浓度", "甲烷浓度", "瓦斯", "甲烷"]},
    "wind_speed": {"label": "风速", "keywords": ["风速", "风量", "风流"]},
    "temperature": {"label": "温度", "keywords": ["温度", "高温", "℃"]},
    "water_level": {"label": "水位", "keywords": ["水位", "涌水量", "积水深度", "水深"]},
    "distance": {"label": "距离", "keywords": ["范围", "距离", "米", "m"]},
    "response_time": {"label": "处置时间", "keywords": ["小时", "分钟", "时限", "时间内"]},
}

DOCUMENT_DEFINITIONS = {
    "safety_regulation": {"label": "安全规程", "keywords": ["规程", "煤矿安全规程", "安全规定"]},
    "emergency_plan": {"label": "应急预案", "keywords": ["应急预案", "处置预案", "救援预案"]},
    "operation_rule": {"label": "作业规程", "keywords": ["作业规程", "操作规程", "施工措施"]},
}

STAGE_DEFINITIONS = {
    "early_warning": {"label": "预警阶段", "keywords": ["预警", "报警", "异常", "征兆"]},
    "initial_response": {"label": "初期处置阶段", "keywords": ["立即", "首先", "初期", "第一时间"]},
    "rescue_response": {"label": "救援处置阶段", "keywords": ["救援", "搜救", "救护队"]},
    "recovery": {"label": "恢复阶段", "keywords": ["恢复", "复工", "确认安全"]},
}

SENSOR_DEFINITIONS = {
    "gas_sensor": {"label": "瓦斯传感器", "keywords": ["瓦斯传感器", "甲烷传感器", "瓦斯检测"]},
    "wind_sensor": {"label": "风速传感器", "keywords": ["风速传感器", "风量监测", "风速监测"]},
    "temperature_sensor": {"label": "温度传感器", "keywords": ["温度传感器", "温度监测"]},
    "water_sensor": {"label": "水位传感器", "keywords": ["水位传感器", "水位监测", "涌水监测"]},
    "power_sensor": {"label": "电气监测装置", "keywords": ["断电仪", "电气监测", "供电监测"]},
}

ENTITY_GROUPS = {
    "document_type": DOCUMENT_DEFINITIONS,
    "hazard": HAZARD_DEFINITIONS,
    "symptom": SYMPTOM_DEFINITIONS,
    "parameter": PARAMETER_DEFINITIONS,
    "sensor": SENSOR_DEFINITIONS,
    "action": ACTION_DEFINITIONS,
    "department": DEPARTMENT_DEFINITIONS,
    "location": LOCATION_DEFINITIONS,
    "equipment": EQUIPMENT_DEFINITIONS,
    "stage": STAGE_DEFINITIONS,
}

RELATION_LABELS = {
    "indicates": "征兆指向灾害",
    "requires_action": "灾害需要措施",
    "responsible_for": "措施归属部门",
    "governed_by": "条款约束措施",
    "occurs_at": "风险发生于场景",
    "supports_action": "证据支撑措施",
    "contains_clause": "文档包含条款",
    "mentions": "条款提及实体",
    "has_parameter": "条款包含参数",
    "triggers_hazard": "参数触发风险",
    "monitors": "监测设备监测对象",
    "in_stage": "动作所属阶段",
    "related_to": "关联",
}
