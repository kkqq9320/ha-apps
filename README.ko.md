# kkqq9320 Home Assistant 앱 모음

[English](README.md)

kkqq9320이 만든 Home Assistant 앱(애드온) 모음이다. 앱은 미리 빌드한 이미지로 설치된다. 앱마다 코드, 시험, 문서는 아래 표의 앱 저장소에 있다.

## 저장소 추가

[이 링크](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fkkqq9320%2Fha-apps)를 열거나, **설정(Settings) → 앱(Apps) → 앱 설치(Install app)**에서 **⋮** 메뉴의 **저장소(Repositories)**를 골라 `https://github.com/kkqq9320/ha-apps`를 추가한다.

## 앱

| 앱 | 설명 | 저장소 |
|---|---|---|
| LG U+ Multitap (MTTL-W01) | 투오 standalone 백엔드를 실행해 LG U+ MTTL-W01 멀티탭이 집 네트워크 안에서 Home Assistant에 접속하게 한다 | [kkqq9320/ha-lgu-mttl-w01](https://github.com/kkqq9320/ha-lgu-mttl-w01) |

## 출처와 라이선스

앱마다 이미지는 앱 저장소에서 빌드한다. 파일의 출처와 라이선스는 그 저장소의 `NOTICE.md`에 있다. 예: [ha-lgu-mttl-w01의 NOTICE.md](https://github.com/kkqq9320/ha-lgu-mttl-w01/blob/main/NOTICE.md).

LG U+ Multitap (MTTL-W01)은 투오의 standalone 백엔드, PC 도구, 안드로이드 설정 앱을 실행하고 다시 배포하며, 대시보드는 [af950833 대시보드](https://github.com/af950833/mttl_w01)의 배치를 가져와 고쳐 썼다.

이 저장소의 README, 도구, workflow는 [MIT 라이선스](LICENSE)를 따른다. 앱 폴더의 파일은 앱 저장소에서 복사한 것이며 그 저장소의 라이선스를 따른다.
