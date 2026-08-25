"""fake_anthropic.py - 不依赖真实 API Key 的 Anthropic SDK mock。

复用 tests/test_compaction_tool_pairs.py 中的 FakeAnthropic 模式，
提供可配置的 messages.create 响应，使基准测试可在无网络/无 Key 环境运行。
"""
import types


class _FakeMessages:
    """模拟 Anthropic client.messages，create() 返回固定响应。"""

    def __init__(self):
        # 配置 create 的默认响应：纯文本 stop
        self._response_factory = None

    def create(self, **kwargs):
        if self._response_factory is not None:
            return self._response_factory(**kwargs)
        # 默认返回一个 stop 文本响应
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="(mock summary)")],
            stop_reason="end_turn",
        )


class FakeAnthropic:
    """模拟 anthropic.Anthropic 客户端，无需 API Key。"""

    def __init__(self, *args, **kwargs):
        self.messages = _FakeMessages()

    def set_response_factory(self, factory):
        """设置自定义响应工厂函数，签名为 factory(**kwargs) -> response。"""
        self.messages._response_factory = factory


def make_fake_anthropic_module():
    """构造一个伪 anthropic 模块对象，注入 sys.modules 后可被 import。"""
    fake = types.ModuleType("anthropic")
    setattr(fake, "Anthropic", FakeAnthropic)
    return fake


def make_fake_dotenv_module():
    """构造一个伪 dotenv 模块对象，提供空 load_dotenv。"""
    fake = types.ModuleType("dotenv")
    setattr(fake, "load_dotenv", lambda override=True: None)
    return fake
