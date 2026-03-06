FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app
COPY main.py .

ENTRYPOINT ["python", "main.py"]
CMD ["--duration", "0", "--interval", "1", "--max-mb", "256"]
