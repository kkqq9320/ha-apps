# ha-apps 저장소 지침

kkqq9320의 Home Assistant 앱 모음 저장소다. 사용자는 이 저장소를 Home Assistant에 추가해 앱을 설치한다. 여기에는 Home Assistant가 읽는 앱 정의만 둔다. 앱 코드, Dockerfile, 시험, 이미지 빌드는 앱마다 개발 저장소가 맡는다. 앱 목록은 `apps.json`(앱 슬러그 → 개발 저장소와 그 안의 앱 폴더 경로)이다.

## 앱 폴더

- 앱 폴더 `<슬러그>/`는 개발 저장소 릴리스 태그 `v<판>`의 정본 파일과 바이트 단위로 같다. 정본 파일은 `config.yaml`, `README.md`, `DOCS.md`, `CHANGELOG.md`, `icon.png`, `logo.png`, `translations/*.yaml`이다(`tools/sync_app.py`의 `REQUIRED`와 `canonical_files`).
- 앱 폴더는 손으로 고치지 않는다. 고칠 것이 있으면 개발 저장소에서 고쳐 새 판으로 릴리스하고, 그 판을 이 저장소로 가져온다.
- 앱 목록 표(README)에는 판 번호를 쓰지 않는다.

## 앱 갱신

개발 저장소가 새 판을 릴리스한 뒤 GitHub Actions의 **Update app** workflow를 실행한다.

```bash
gh workflow run update-app.yml -f app=mttl_w01 -f version=<판>
```

- `update-app.yml`은 `apps.json` 확인, 개발 저장소 태그 `v<판>`의 정본 파일 확인(`version`, `slug`, `image`), GHCR 이미지를 익명으로 받을 수 있는지와 `linux/amd64`·`linux/arm64`가 모두 있는지, 앱 설정 검사기를 거친 뒤 가지 `update/<슬러그>-<판>`에 커밋하고 PR을 연다.
- 검사 작업(`check`)은 읽기 전용 토큰으로 돌고, PR 작업(`pr`)만 쓰기 권한을 받는다. PR 작업은 GitHub의 `actions/*`만 쓰고 앱 폴더를 릴리스에서 다시 만든다. 외부 검사기 액션이 쓰기 토큰에 닿지 않게 하려는 것이다. 이 구분을 유지한다.
- `GITHUB_TOKEN`으로 연 PR에서는 다른 workflow가 돌지 않는다. 그래서 검사를 `update-app.yml` 안에서 한다. 병합하면 `main` push로 `ci.yml`이 다시 돈다.
- PR의 바뀐 파일이 앱 폴더의 정본 파일뿐인지 확인하고 병합한다. 병합이 곧 배포다. Home Assistant는 이 저장소의 기본 가지를 읽는다.
- 저장소 설정에서 "Allow GitHub Actions to create and approve pull requests"를 켜 두어야 PR이 열린다.
- `ci.yml`(push·PR)은 시험, 앱 폴더와 릴리스 태그 비교, 이미지 확인(`python tools/sync_app.py check`), 앱 설정 검사기를 돈다.
- 로컬에서 네트워크 없이 확인할 때는 개발 저장소 checkout을 원본으로 쓴다: `python tools/sync_app.py --repo <사본> update mttl_w01 <판> --source <개발 저장소> --skip-image`. 실제 저장소의 앱 폴더는 workflow PR로만 바꾼다.

## 새 앱 더하기

1. `apps.json`에 앱 슬러그, 개발 저장소(`<owner>/<repo>`), 앱 폴더 경로를 적는다. 폴더가 아직 없는 앱은 검사가 "아직 내지 않은 앱"(`not released yet`)으로 넘어간다.
2. 개발 저장소에서 첫 판을 릴리스하고 GHCR 패키지를 공개로 바꾼다.
3. [앱 갱신](#앱-갱신)으로 앱 폴더를 가져온다.
4. README 짝 파일의 앱 표에 줄을 더한다.

## 코드 규칙

- `tools/`, `tests/`의 Python은 표준 라이브러리만 쓴다.
- 줄바꿈은 LF다. `.gitattributes`가 정한다.
- 도구 출력은 영어로 쓴다. 사용자 문서는 영어 `README.md`와 한국어 `README.ko.md` 짝이다. 이 파일은 관리자용이므로 한국어로 쓴다.

## 시험

```bash
python -m unittest discover -s tests -v
```

## 저장소에 넣지 않는 것

- 앱 코드, Dockerfile, 앱 시험. 개발 저장소에 둔다.
- 다른 저장소에 쓸 수 있는 토큰(PAT, GitHub App 비밀값). workflow는 이 저장소의 `GITHUB_TOKEN`만 쓴다.
- 집 네트워크 주소, 개인 PC 경로, 인수인계·조사 기록
