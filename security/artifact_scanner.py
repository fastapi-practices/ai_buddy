from pydantic_ai_harness.artifact_scanning import ArtifactScanResult, ArtifactScanner

# 跨会话持久化的产物共用同一份扫描规则，模型写入和后续加载都走这里
buddy_artifact_scanner: ArtifactScanner = ArtifactScanner()


def scan_artifact(content: str, *, source: str) -> ArtifactScanResult:
    """
    扫描模型写入的产物，识别提示注入、凭据外泄和隐藏内容

    :param content: 产物正文
    :param source: 产物来源标记
    :return:
    """
    return buddy_artifact_scanner.scan(content, source=source)


def artifact_scan_notice(result: ArtifactScanResult) -> str:
    """
    生成可交给模型的拒收说明，只描述威胁类型不回显原文

    :param result: 扫描结果
    :return:
    """
    return f'内容包含风险特征（{result.summary()}），已拒绝写入，请改写后再试'
