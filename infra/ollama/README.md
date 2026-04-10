# Ollama — modelos LicitAI (num_ctx 12k)

El backend ya envía `num_ctx` vía API (`OLLAMA_NUM_CTX`, por defecto 12288). Este directorio versiona **Modelfiles** para que el daemon de Ollama use la misma ventana al cargar el modelo.

## Coder (recomendado hardening)

Con el tag estándar ya descargado (`qwen2.5-coder:7b`):

```bash
ollama create licitai-coder -f infra/ollama/Modelfile.licitai-coder
```

Variante **q5** (menos VRAM), tras `ollama pull qwen2.5-coder:7b-instruct-q5_K_M`:

```bash
ollama create licitai-coder-q5 -f infra/ollama/Modelfile.licitai-coder-q5
```

En `.env` / `docker-compose`: `OLLAMA_MODEL=licitai-coder` (o `licitai-coder-q5`).

## Llama (compatibilidad con el default histórico del repo)

```bash
ollama pull llama3.1:8b
ollama create licitai-llama -f infra/ollama/Modelfile.licitai-llama
```

`OLLAMA_MODEL=licitai-llama`

## PowerShell (desde la raíz del repo `licitaciones-ai`)

```powershell
ollama create licitai-coder -f infra/ollama/Modelfile.licitai-coder
```
