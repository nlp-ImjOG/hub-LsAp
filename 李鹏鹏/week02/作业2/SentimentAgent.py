import json
from openai import OpenAI

model_name = "MiniMax-M3"

ai_client = OpenAI(
    api_key="sk-cp-mEeFZRSWbWzFdg5og740Eac0Lu1fZGO2yo_O2EBqleWlXqT7JOM51DnnL76FaTz9wgKgwiwb74QAj8ujsXgsJ2QHvkrbVAjRb4QVCpYSJzDLDTSS2rF0dWw",
    base_url="https://api.minimaxi.com/v1"
)


# ═════════════════════════════════════════════════════════════════════════════
# 0. 定义本地工具函数
# ═════════════════════════════════════════════════════════════════════════════

def save_relationship_graph(relationships: list[dict]) -> str:
    """保存并返回人物关系图谱。"""
    print(f"\n    📊  解析得到 {len(relationships)} 条人物关系：")
    for i, r in enumerate(relationships, 1):
        print(f"      {i}. {r.get('source')}  --[{r.get('relation')}]-->  {r.get('target')}")
    return json.dumps(relationships, ensure_ascii=False)


# ═════════════════════════════════════════════════════════════════════════════
# 工具描述 schema（传给模型）
# ═════════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_relationship_graph",
            "description": (
                "将文本中提取出的人物情感关系三元组（source-relation-target）"
                "保存为结构化图谱。仅在模型完成全部抽取后调用一次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relationships": {
                        "type": "array",
                        "description": "人物关系列表，每条是一个三元组",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {
                                    "type": "string",
                                    "description": "关系主体（谁发出情感/动作）",
                                },
                                "relation": {
                                    "type": "string",
                                    "description": "情感或关系类型，如：爱慕、喜欢、讨厌、朋友、敌对",
                                },
                                "target": {
                                    "type": "string",
                                    "description": "关系客体（情感或动作的承受者）",
                                },
                            },
                            "required": ["source", "relation", "target"],
                        },
                    },
                },
                "required": ["relationships"],
            },
        },
    }
]

# 工具名 → 本地函数映射
FUNCTION_MAP = {
    "save_relationship_graph": save_relationship_graph
}


def run_tool_call(toolcall) -> str:
    """执行一次工具调用，返回结果字符串。"""
    name = toolcall.function.name
    args_value = json.loads(toolcall.function.arguments)
    print(f"    → 调用工具: {name}({json.dumps(args_value, ensure_ascii=False)})")
    result_value = FUNCTION_MAP[name](**args_value)
    print(f"    ← 结果: {result_value}")
    return result_value


messages = [
    {"role": "system", "content": "你是人物关系分析助手，负责从用户的中文文本中识别'人物'与'人物之间的情感/关系'"},
    {"role": "user", "content": "小明喜欢小姚，但是小姚喜欢小王。"}
]

response = ai_client.chat.completions.create(
    model=model_name,
    messages=messages,
    tools=TOOLS,
    temperature=0.0,
    extra_body={"thinking": {"type": "disabled"}}
)

msg = response.choices[0].message

relationships = list()

# 模型可能直接回复（不需要工具），也可能发起工具调用
if msg.tool_calls:
    for tc in msg.tool_calls:
        result = run_tool_call(tc)
        args = json.loads(tc.function.arguments)
        relationships = args.get("relationships", list())
        messages.append(msg)  # 保留 assistant 的 tool_calls
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result,
        })

    # 把工具结果发回模型，让其生成最终回复
    final = ai_client.chat.completions.create(
        model=model_name,
        messages=messages,
        tools=TOOLS,
        temperature=0.0,
    )
    print(f"\n最终回复: \n {final.choices[0].message.content}")
else:
    print(f"直接回复: {msg.content}")

print(f"\n人物关系图：\n {json.dumps(relationships, ensure_ascii=False, indent=4)}")
