# Security

Textorium runs locally: the web edition's Content-Security-Policy blocks every network request, and the
desktop edition imports no network modules. Imported fonts, images, SVGs and project files are treated as
untrusted (size limits, magic-byte checks, SVG sanitising, no `eval`).

If you find a way around any of that, please report it privately through
**Security → Report a vulnerability** on this repository rather than in a public issue.
