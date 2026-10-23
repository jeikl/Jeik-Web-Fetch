import pytest
from jeik_web_fetch.cli import build_parser
from jeik_web_fetch.core.models import FetchMode

def test_cli_mode_flags():
    parser = build_parser()

    # 测试默认缺省为 --fast
    args_default = parser.parse_args(["fetch", "https://example.com"])
    assert args_default.mode == FetchMode.FAST

    # 测试显式 --fast
    args_fast = parser.parse_args(["fetch", "https://example.com", "--fast"])
    assert args_fast.mode == FetchMode.FAST

    # 测试显式 --common
    args_common = parser.parse_args(["fetch", "https://example.com", "--common"])
    assert args_common.mode == FetchMode.COMMON

    # 测试显式 --complex
    args_complex = parser.parse_args(["fetch", "https://example.com", "--complex"])
    assert args_complex.mode == FetchMode.COMPLEX

def test_cli_mode_mutually_exclusive():
    parser = build_parser()
    # 测试互斥参数同时传入时引发 SystemExit
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "https://example.com", "--fast", "--common"])
