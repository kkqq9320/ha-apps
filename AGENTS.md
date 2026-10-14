# ha-apps 저장소 지침

kkqq9320의 Home Assistant 앱 모음 저장소다. 사용자는 이 저장소를 Home Assistant에 추가해 앱을 설치한다. 여기에는 Home Assistant가 읽는 앱 정의만 둔다. 앱 코드, Dockerfile, 시험, 이미지 빌드는 앱마다 개발 저장소가 맡는다. 앱 목록은 `apps.json`(앱 슬러그 → 개발 저장소와 그 안의 앱 폴더 경로)이다.

## 앱 폴더

- 앱 폴더 `<슬러그>/`는 개발 저장소 릴리스 태그 `v<판>`의 정본 파일과 바이트 단위로 같다. 정본 파일은 `config.yaml`, `README.md`, `DOCS.md`, `CHANGELOG.md`, `icon.png`, `logo.png`, `translations/*.yaml`이다(`tools/sync_app.py`의 `REQUIRED`와 `canonical_files`).
- 앱 폴더는 손으로 고치지 않는다. 고칠 것이 있으면 개발 저장소에서 고쳐 새 판으로 릴리스하고, 그 판을 이 저장소로 가져온다.
- 앱 목록 표(README)에는 판 번호를 쓰지 않는다.

## 새 앱 더하기

1. `apps.json`에 앱 슬러그, 개발 저장소(`<owner>/<repo>`), 앱 폴더 경로를 적는다. 폴더가 아직 없는 앱은 검사가 "아직 내지 않은 앱"으로 넘어간다.
2. 개발 저장소에서 첫 판을 릴리스하고 GHCR 패키지를 공개로 바꾼다.
3. 그 판을 이 저장소로 가져온다.
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
