---
name: Google Drive API v3 (REST)
description: Referência REST da Google Drive API v3 — recursos, métodos e, em especial, download e exportação de arquivos (files.get_media, files.export, files.download/LRO), operações, escopos, formatos de export e erros. Use ao integrar, projetar ou depurar acesso ao Google Drive.
---

# Google Drive API v3 — referência REST

Fonte oficial: <https://developers.google.com/workspace/drive/api/reference/rest/v3>

- **Service endpoint:** `https://www.googleapis.com`
- **Discovery doc:** `https://www.googleapis.com/discovery/v1/apis/drive/v3/rest`
- **Client library (Python):** `google-api-python-client`, `build("drive", "v3", credentials=..., cache_discovery=False)`

## Recursos e métodos (v3)

| Recurso | Métodos |
| --- | --- |
| `about` | `get` |
| `accessproposals` | `get`, `list`, `resolve` |
| `approvals` | `approve`, `cancel`, `comment`, `decline`, `get`, `list`, `reassign`, `start` |
| `apps` | `get`, `list` |
| `changes` | `getStartPageToken`, `list`, `watch` |
| `channels` | `stop` |
| `comments` | `create`, `delete`, `get`, `list`, `update` |
| `drives` | `create`, `delete`, `get`, `hide`, `list`, `unhide`, `update` |
| `files` | `copy`, `create`, `delete`, `download`, `emptyTrash`, `export`, `generateCseToken`, `generateIds`, `get`, `list`, `listLabels`, `modifyLabels`, `update`, `watch` |
| `operations` | `get` |
| `permissions` | `create`, `delete`, `get`, `list`, `update` |
| `replies` | `create`, `delete`, `get`, `list`, `update` |
| `revisions` | `delete`, `get`, `list`, `update` |

Os códigos usados pelo AgeBackup: `files.list` (listar), `files.get`
(metadados), `files.get_media` (blob), `files.export` (nativo pequeno),
`files.download` (nativo grande / LRO) e `operations.get` (consultar a LRO).

## Baixar vs. exportar — a parte que importa

Há **duas famílias** de arquivos no Drive:

1. **Blobs** (enviados): PDF, imagem, vídeo, `.docx`/`.xlsx` enviados, `.md`, etc.
   Têm conteúdo binário próprio.
2. **Nativos do Google Workspace** (`application/vnd.google-apps.*`): Docs,
   Sheets, Slides, Desenhos, Vids. **Não têm conteúdo binário** — precisam ser
   *exportados* para um formato.

### `files.get_media` — baixar blob

```
GET https://www.googleapis.com/drive/v3/files/{fileId}?alt=media
```

- Para blobs, de qualquer tamanho (sem limite de 10 MB).
- Em nativos, devolve **403** (`fileNotDownloadable` / "Use Export").
- Na client library: `service.files().get_media(fileId=...)` → usar com
  `MediaIoBaseDownload` (chunks). **Não** use `.execute()` (carrega tudo na RAM).

### `files.export` — exportar nativo (tem limite de 10 MB)

```
GET https://www.googleapis.com/drive/v3/files/{fileId}/export?mimeType={mime}&alt=media
```

- Para Docs/Sheets/Slides/Desenhos.
- **Limite de 10 MB por requisição.** Acima disso → **403**
  `exportSizeLimitExceeded`.
- Não suporta download parcial.
- Na client library: `service.files().export_media(fileId=..., mimeType=...)`.

### `files.download` — operação de longa duração (LRO), **sem o limite de 10 MB**

```
POST https://www.googleapis.com/drive/v3/files/{fileId}/download?mimeType={mime}
```

- Devolve uma **Operation**; quando concluída, traz
  `response.downloadUri` (uma URL em `docs.google.com/feeds/download/...`).
- **Não tem o limite de 10 MB** do `files.export` — é o caminho para nativos
  grandes (testado: Slide de ~12 MB → `.pptx` de ~16 MB).
- É **o único** caminho para formatos que o export recusa (ex.: **Google Vids**,
  `application/vnd.google-apps.video` → `video/mp4`).
- Exige só **`drive.readonly`** (não precisa das APIs nativas Slides/Docs/Sheets).
- `?alt=media` neste endpoint devolve **400** — o certo é o POST → `downloadUri`.
- O `mimeType` só pode ser informado para documentos do Workspace; sem ele, o
  documento é baixado num formato padrão (que pode mudar sem aviso).

Fluxo (na client library):

```python
req = service.files().download(fileId=file_id, mimeType=mime)   # POST
op = req.execute()                       # {"done": true, "response": {"downloadUri": ...}}
while not op.get("done"):                # normalmente já vem pronto
    op = consultar_operacao(op["name"])  # GET /drive/v3/operations/{name}
uri = op["response"]["downloadUri"]
# GET na uri com o mesmo transporte autenticado (req.http), streaming em chunks
```

Notas:
- `downloadUri` costuma apontar para `docs.google.com/feeds/download/...` e
  **pode redirecionar**; o transporte autenticado precisa seguir o redirect
  mantendo o `Authorization: Bearer`.
- `response.partialDownloadAllowed` indica se dá para retomar (`false` para
  documentos).
- Passe `supportsAllDrives=true` para arquivos em shared drives.

### `operations.get` — consultar a LRO

```
GET https://www.googleapis.com/drive/v3/operations/{name}
```

- `name` é opaco; URL-encode ao montar a URL.
- Operation: `{ name, done, metadata, response?, error? }`. Cheque `done` e, se
  houver `error`, trate como falha (não é HTTP error).

## Formatos de export (nativos → destino)

Fonte: <https://developers.google.com/workspace/drive/api/guides/ref-export-formats>

| Nativo | Formatos comuns |
| --- | --- |
| Documento | `.docx`, `.odt`, `.pdf`, `.txt`, **`.md`** (`text/markdown`), `.html`, `.rtf`, `.epub` |
| Planilha | `.xlsx`, `.ods`, `.pdf`, **CSV/TSV (só a 1ª aba)**, `.html` |
| Apresentação | `.pptx`, `.odp`, `.pdf`, **`.txt`** |
| Desenho | `.pdf`, `.png`, `.jpg`, `.svg` |
| Script | `.json` (Apps Script) |

- Planilha → CSV/TSV perde as demais abas (exporta só a primeira), então **não**
  serve como backup fiel.
- Docs → `.md`/`.txt` funciona pela própria Drive API (dispensa a Docs API).

## Escopos

| Escopo | Permite |
| --- | --- |
| `drive.readonly` | Ler metadados + baixar/exportar/`files.download` |
| `drive.file` | Só arquivos criados/abertos pelo app |
| `drive` (completo) | Tudo (evitar para backup) |

As APIs nativas (Slides/Docs/Sheets) exigem escopos próprios
(`presentationId`/`documentId`/`spreadsheetId`) e **APIs habilitadas** no
projeto; o `files.download` **não** exige nada disso.

## Erros comuns

| HTTP | reason | Significado |
| --- | --- | --- |
| 403 | `exportSizeLimitExceeded` | `files.export` > 10 MB → usar `files.download` |
| 403 | `fileNotDownloadable` / "Use Export" | `get_media` num nativo → usar export/download |
| 403 | `fileNotExportable` | Formato sem export (ex.: Vids) → usar `files.download` |
| 403 | `insufficientFilePermissions` | Sem permissão de leitura |
| 403 | `appNotAuthorizedToFile` | Arquivo fora do escopo `drive.file` |
| 403 | `cannotDownloadAbusiveContent` | Bloqueado por política |
| 403 | `rateLimitExceeded` / 429 | Throttling → repetir (backoff) |
| 404 | `notFound` | Não existe / sem acesso |
| 5xx | — | Repetir |

`SERVICE_DISABLED` (403) vem das **APIs nativas** (Slides/Docs/Sheets)
desabilitadas — **não** afeta `files.download`.

## Boas práticas

- Liste com `files.list`, `fields="nextPageToken, files(id,name,mimeType,size,modifiedTime,parents)"`
  e pagine com `pageSize`/`pageToken` (100 por página).
- Peça só os `fields` que precisa.
- Dois erros "403 permissão" podem se disfarçar de "grande demais": cheque o
  `reason` (`exportSizeLimitExceeded`), não só o status.
- Para streaming de arquivos grandes, use `MediaIoBaseDownload` com `chunksize`
  e gravação atômica (`.tmp` + `os.replace`).
- Fluxo robusto para um nativo: `files.export` (rápido) → no
  `exportSizeLimitExceeded`, `files.download` (LRO, sem limite) → PDF → só então
  reconstrução/erro.

## Ver também

- Baixar e exportar: <https://developers.google.com/workspace/drive/api/guides/manage-downloads>
- Operações de longa duração: <https://developers.google.com/workspace/drive/api/guides/long-running-operations>
- `files.download`: <https://developers.google.com/workspace/drive/api/reference/rest/v3/files/download>
- Formatos de export: <https://developers.google.com/workspace/drive/api/guides/ref-export-formats>
- Limites de uso: <https://developers.google.com/workspace/drive/api/guides/limits>
