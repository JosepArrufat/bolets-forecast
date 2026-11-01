FROM python:3.12-slim
WORKDIR /app
COPY app.py mushrooms.json ./
RUN mkdir -p /app/data
ENV PORT=8080
EXPOSE 8080
CMD ["python3", "app.py"]
