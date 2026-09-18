docker build -t gridwise:latest .

docker run --rm \
  -p 8000:8000 \
  -e LLM_API_URL="<provider endpoint>" \
  -e LLM_API_KEY="<secret>" \
  -e LLM_MODEL="<model>" \
  gridwise:latest

  