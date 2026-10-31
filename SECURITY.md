# Review isolation

No inherited Git history is included. Google-key literals, environment files,
identity backups, uploads and runtime data are excluded. Old repositories and
public branches retain historical/current exposures and need separate owner action.
No GitHub Actions workflows, CNAME, production host configuration or deployment
scripts are included. Connected GitHub Apps/external watchers still require scope
review before new private repository publication. No production service may be
contacted by this local validation. Tests use disposable state and network mocks.
