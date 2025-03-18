cd ~/agilab
clear

# upgrade
pushd fwk/env; uv sync --upgrade; uv add --dev .; uv pip -e .; popd
pushd fwk/core/managers; uv sync --upgrade; uv add --dev .; uv pip -e .; popd
pushd fwk/AGILab; uv sync --upgrade --groups Agi; uv add --dev .; uv pip -e .; popd
pushd apps/flight-project; uv sync --upgrade --groups rapids; uv add --dev .; uv pip -e .; popd
pudhd apps/my-code-porject; uv sync --upgrade --groups rapids; uv add --dev .; uv pip -e .; popd