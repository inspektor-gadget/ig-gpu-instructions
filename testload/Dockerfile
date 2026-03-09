FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app
COPY main.py .
ENV PYTORCH_NO_CUDA_MEMORY_CACHING=1
ENV PYTHON_JIT=0

CMD ["python", "main.py"]
