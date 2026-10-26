from typing import Any

from jsonschema import ValidationError
from jsonschema.validators import validator_for
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.tools import ArgsValidatorFunc
from referencing import Registry
from referencing.exceptions import Unresolvable


def build_tool_args_validator(schema: dict[str, Any]) -> ArgsValidatorFunc[Any, ...]:
    """
    在动态工具审批和执行前按原始 JSON Schema 校验参数，不读取外部引用

    :param schema: 参数模式
    :return:
    """
    validator_type = validator_for(schema)
    validator_type.check_schema(schema)
    validator = validator_type(schema, registry=Registry())

    def validate(_ctx: RunContext[Any], **arguments: Any) -> None:
        """
        把参数错误交回模型修正

        :param arguments: 工具参数
        :return:
        """
        try:
            validator.validate(arguments)
        except ValidationError as exc:
            raise ModelRetry(f'Invalid tool arguments at {exc.json_path}: {exc.message}') from exc
        except (Unresolvable, RecursionError) as exc:
            raise ModelRetry('Tool argument schema contains an unsupported reference') from exc

    return validate
