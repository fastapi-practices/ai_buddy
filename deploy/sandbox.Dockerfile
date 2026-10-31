ARG DOCX_CLI_VERSION=v0.28.0
ARG DOCX_CLI_BASE_URL=https://github.com/kklimuk/docx-cli/releases/download
ARG DOCX_CLI_SHA256_AMD64=e540eacc28dff30a61d502d1a24b7ebde53586295fd5c6a213e74458c4a0ad92
ARG DOCX_CLI_SHA256_ARM64=68a91b828cd1f61cd67a254198dbbc6a421d99c950525fd9cfeb2bef956fa947

FROM node:22-bookworm-slim AS node

# docx-cli 按架构拉取并校验，github.com 不可达时用 --build-arg DOCX_CLI_BASE_URL 指向镜像站
FROM scratch AS docx-cli-amd64
ARG DOCX_CLI_VERSION
ARG DOCX_CLI_BASE_URL
ARG DOCX_CLI_SHA256_AMD64
ADD --checksum=sha256:${DOCX_CLI_SHA256_AMD64} --chmod=755 ${DOCX_CLI_BASE_URL}/${DOCX_CLI_VERSION}/docx-linux-x64 /docx

FROM scratch AS docx-cli-arm64
ARG DOCX_CLI_VERSION
ARG DOCX_CLI_BASE_URL
ARG DOCX_CLI_SHA256_ARM64
ADD --checksum=sha256:${DOCX_CLI_SHA256_ARM64} --chmod=755 ${DOCX_CLI_BASE_URL}/${DOCX_CLI_VERSION}/docx-linux-arm64 /docx

FROM docx-cli-${TARGETARCH} AS docx-cli

FROM scratch AS docx-cli-notices
ARG DOCX_CLI_VERSION
ARG DOCX_CLI_BASE_URL
# docx 二进制静态链接了 LGPL-3.0 的 libheif-js，随二进制分发许可证与声明
ADD --chmod=644 --checksum=sha256:7fa7b3c657b4ac3370075c5404fa97ac2c38ea8631bae6f5938b5ec3aac40a75 ${DOCX_CLI_BASE_URL}/${DOCX_CLI_VERSION}/LICENSE /LICENSE
ADD --chmod=644 --checksum=sha256:3e1627e675741c458fa4c1d0126e92061c8fccaabe3d13407cffa85a4775fce1 ${DOCX_CLI_BASE_URL}/${DOCX_CLI_VERSION}/NOTICES /NOTICES
ADD --chmod=644 --checksum=sha256:e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118 ${DOCX_CLI_BASE_URL}/${DOCX_CLI_VERSION}/LGPL-3.0.txt /LGPL-3.0.txt

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git bash ca-certificates libatomic1 libstdc++6 fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/ /usr/local/
COPY --from=node /opt/ /opt/

# 文档处理依赖随镜像预装，沙箱默认禁止出网，技能脚本不能在运行时安装；版本与插件 requirements.txt 保持一致
RUN pip install --no-cache-dir \
        office-oxide==0.1.15 pypdf==6.21.4 pypdfium2==5.14.0 pdfplumber==0.11.10 reportlab==5.1.0 \
        pandas==3.1.0 openpyxl==3.1.5 pillow==13.0.0 \
    && npm install -g pptxgenjs@4.0.1 \
    && npm cache clean --force
ENV NODE_PATH=/usr/local/lib/node_modules

COPY --from=docx-cli /docx /usr/local/bin/docx
COPY --from=docx-cli-notices / /usr/share/doc/docx-cli/

WORKDIR /workspace
