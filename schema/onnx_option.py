from pydantic import Field

from backend.common.schema import SchemaBase


class GetAIBuddyOnnxOptionDetail(SchemaBase):
    """本地 ONNX 选项"""

    id: str = Field(description='选项 ID')
    name: str = Field(description='显示名称')
    size_gb: float | None = Field(None, description='大约体积 GB')
    downloaded: bool = Field(description='是否已下载')


class GetAIBuddyOnnxCatalogDetail(SchemaBase):
    """本地 ONNX 目录"""

    embedding: list[GetAIBuddyOnnxOptionDetail] = Field(description='向量模型')
    ocr: list[GetAIBuddyOnnxOptionDetail] = Field(description='OCR 模型')
    paddleocr: list[GetAIBuddyOnnxOptionDetail] = Field(description='本机 PaddleOCR 模型')
    cache_dir: str = Field(description='向量模型固定目录')
    ocr_cache_dir: str = Field(description='OCR 模型固定目录')
    paddleocr_cache_dir: str = Field(description='PaddleOCR 模型固定目录')


class DownloadAIBuddyOnnxParam(SchemaBase):
    """下载 ONNX 向量模型"""

    model_id: str = Field(description='模型 ID')


class GetAIBuddyOnnxDownloadStatusDetail(SchemaBase):
    """ONNX 下载状态"""

    status: str = Field(description='idle / downloading / done / failed')
    progress: float = Field(description='进度 0-1')
    model_id: str = Field(description='模型 ID')
    error: str | None = Field(None, description='失败原因')
    cache_dir: str = Field(description='向量模型固定目录')
