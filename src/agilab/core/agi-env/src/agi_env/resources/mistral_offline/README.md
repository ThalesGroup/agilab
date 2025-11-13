# Mistral Offline Reference Data

The original repository included ~70 MB of PDF cheat sheets that were only used
as reference material for the offline Mistral demo. Those binaries have been
removed from Git to keep clone sizes reasonable.

To restore the optional reference pack:

1. Download the `mistral_offline_data.zip` bundle from the internal AGI asset
   share (see the “Offline assets” Confluence page for the latest link).
2. Extract the archive into this directory so that the PDF files land under
   `mistral_offline/data/`.

The `.gitignore` in `mistral_offline/data/` prevents re-adding the large files,
so you can safely extract updates there without affecting future commits.
