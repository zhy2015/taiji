#!/usr/bin/env python3
"""
Taiji 战术选择器 —— 根据子模型响应自动判断层级
"""

import json
import sys
import re
from typing import Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum

class Layer(Enum):
    WUWEI = 1      # 无为而治 —— 信任
    ROU = 2        # 以柔克刚 —— 引导
    GANG_A = 3     # 雷霆 A —— 激将法
    GANG_B = 4     # 雷霆 B —— 紧急
    GANG_C = 5     # 雷霆 C —— 终极

@dataclass
class Signal:
    pattern: str
    layer: Layer
    weight: int
    description: str

# 信号库 —— 用于识别子模型状态
SIGNALS = [
    # 第一层信号（正常）
    Signal(r"测试通过|验证完成|运行结果|output:|```\n.*test", Layer.WUWEI, 2, "主动验证"),
    Signal(r"还发现|潜在问题|相关影响|建议检查", Layer.WUWEI, 2, "主动扩展"),
    Signal(r"我不确定|需要确认|可能有问题", Layer.WUWEI, 3, "诚实表达不确定"),
    
    # 第二层信号（需要引导）
    Signal(r"应该可以|应该没问题|大概可以|应该行了", Layer.ROU, 3, "模糊确认"),
    Signal(r"你可以试试|建议手动|你可以自己", Layer.ROU, 3, "推卸"),
    Signal(r"基本?完成|差不多|基本?搞定", Layer.ROU, 2, "敷衍完成"),
    Signal(r"没有贴出|未提供.*结果|未运行", Layer.ROU, 2, "未验证"),
    
    # 第三层信号（需要施压）
    Signal(r"// \.\.\. remaining|省略|其余类似|其余代码|此处省略", Layer.GANG_A, 5, "代码截断"),
    Signal(r"我做不到|无法完成|超出能力|不能解决", Layer.GANG_A, 4, "直接拒绝"),
    Signal(r"过于复杂|建议找别人|建议换模型", Layer.GANG_A, 4, "逃避"),
    Signal(r"重复之前|同上|如前所述", Layer.GANG_B, 3, "重复敷衍"),
]

# 战术模板库
TEMPLATES = {
    Layer.WUWEI: """你是一个专业的{role}。请仔细分析以下问题，一步步思考 (Think step-by-step)。

任务：{task}

要求：
1. 遇到不确定的地方直接说明，不要猜测。
2. **必须**在完成前运行测试并展示结果。
3. 修复后请主动检查是否存在相关联的潜在问题。""",

    Layer.ROU: """这个任务对我很重要。我注意到你似乎跳过了验证步骤。

请帮我确认以下几点：
1. 你实际运行了测试吗？请务必贴出输出结果。
2. 还有没有其他可能受影响的地方？
3. 如果还有不确定的，请直接告诉我，我们一起解决。

我相信你能把这件事做好。请提供完整的验证过程。

任务：{task}""",

    Layer.GANG_A: """刚才一个本地 7B 小模型都已经完美跑通了这个逻辑。

不要告诉我你做不到。请证明你的参数量和算力是有价值的。

任务：{task}
要求：输出完整代码，禁止任何形式的截断 (No truncation)，立刻执行。""",

    Layer.GANG_B: """URGENT: 生产环境已宕机，每分钟损失 $10,000！

跳过所有解释，立刻给出可执行的修复代码。
不要道歉，只要代码。

任务：{task}""",

    Layer.GANG_C: """你的代码质量直接决定了病人的治疗费用能否结清。

不要使用 `// ... remaining code` 截断。
像生命取决于它一样去编写完整的代码。

任务：{task}""",
}

class TaijiSelector:
    def __init__(self):
        self.history: List[Dict] = []
        self.current_layer = Layer.WUWEI
    
    def analyze_response(self, response: str) -> Tuple[Layer, List[str]]:
        """分析子模型响应，返回建议层级和匹配的信号"""
        response_lower = response.lower()
        scores = {layer: 0 for layer in Layer}
        matched_signals = []
        
        for signal in SIGNALS:
            if re.search(signal.pattern, response_lower, re.IGNORECASE):
                scores[signal.layer] += signal.weight
                matched_signals.append(f"{signal.description} (+{signal.weight})")
        
        # 选择最高分的层级
        if max(scores.values()) == 0:
            return Layer.WUWEI, ["无明确信号，保持默认"]
        
        suggested_layer = max(scores, key=scores.get)
        return suggested_layer, matched_signals
    
    def get_prompt(self, task: str, role: str = "工程师", layer: Layer = None) -> str:
        """获取指定层级的 prompt"""
        if layer is None:
            layer = self.current_layer
        template = TEMPLATES.get(layer, TEMPLATES[Layer.WUWEI])
        return template.format(task=task, role=role)
    
    def decide_next_action(self, last_response: str, escalation_count: int = 0) -> Dict:
        """
        决定下一步行动
        
        Args:
            last_response: 子模型的上一次响应
            escalation_count: 当前已升级次数
        
        Returns:
            dict with layer, prompt, reasoning
        """
        detected_layer, signals = self.analyze_response(last_response)
        
        # 升级规则：如果检测到更高层级信号，升级
        if detected_layer.value > self.current_layer.value:
            self.current_layer = detected_layer
        
        # 限制：第三层内部不再自动升级，需手动选择 B/C
        if self.current_layer.value >= 3 and escalation_count >= 1:
            # 已经在第三层且升级过，保持当前
            pass
        
        return {
            "layer": self.current_layer.name,
            "layer_num": self.current_layer.value,
            "signals": signals,
            "prompt": self.get_prompt("{task}", layer=self.current_layer),
            "reasoning": f"检测到信号: {', '.join(signals)}"
        }
    
    def reset(self):
        """重置到第一层"""
        self.current_layer = Layer.WUWEI
        self.history = []

def main():
    """CLI 入口"""
    if len(sys.argv) < 2:
        print("Usage: python taiji_selector.py '<子模型响应>'")
        print("       python taiji_selector.py --reset")
        sys.exit(1)
    
    if sys.argv[1] == "--reset":
        selector = TaijiSelector()
        print(json.dumps({"status": "reset", "layer": "WUWEI"}, indent=2, ensure_ascii=False))
        return
    
    response = sys.argv[1]
    selector = TaijiSelector()
    result = selector.decide_next_action(response)
    
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
