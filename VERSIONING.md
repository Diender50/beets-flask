# Versioning Strategy

Follow [Semantic Versioning 2.0.0](https://semver.org/)

## Current Version: 1.3.0-dev (next release target)

Based on fork from v1.2.1, with additions:
- **Artist Discovery Flow** (feat): squidwtf provider integration, ALTCHA solver, phase 1-2 completion
- **UI/UX Improvements**: Artist UI refactoring, discovery popup cleanup
- **Bug Fixes**: Edge cases in discovery flow

## Release Branch Strategy

| Branch | Tag | When | Docker Tag |
|--------|-----|------|-----------|
| `main` | `vX.Y.Z` (non-pre) | Stable release | `stable`, `latest`, `X.Y.Z` |
| `develop` | N/A | Continuous dev | `dev` |

## Release Process

1. **Feature Development**: Commit to `develop` branch
   ```bash
   git checkout develop
   git commit -m "feat(discovery): add new feature"
   ```

2. **Release Candidate**: Tag on `develop` or `main`
   ```bash
   git tag v1.3.0-rc1
   git push origin v1.3.0-rc1
   ```
   Docker tag: `rc`, `1.3.0-rc1`

3. **Stable Release**: Tag on `main`
   ```bash
   git tag v1.3.0
   git push origin v1.3.0
   ```
   Docker tags: `stable`, `latest`, `1.3.0`

## Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: artist discovery flow phase 1-2
fix: edge case in search candidates  
docs: update versioning guide
chore: update dependencies
```

Map to semver:
- `feat:` → MINOR bump
- `fix:` → PATCH bump
- `BREAKING CHANGE:` → MAJOR bump

## Docker Image Publishing

GitHub Actions auto-builds on:
- Push to `develop` → `dev` tag
- Push to `main` → no auto-tag (manual via git tag)
- Git tag `vX.Y.Z` → `stable` + `latest` + `X.Y.Z` tags
- Git tag `vX.Y.Z-*` → `rc` tag for pre-releases

Registry: `ghcr.io/${{ github.repository }}`

## Changelog

Update [CHANGELOG.md](CHANGELOG.md) before release:
```markdown
## [1.3.0] - YYYY-MM-DD

### Added
- Artist discovery flow with squidwtf provider integration

### Changed
- UI refactoring for artist interface

### Fixed
- Edge cases in discovery search
```
