# Changelog

## 3.0.0.b8 - 2026-02-28

### <!-- 01 -->💡 Features

- Improve command line help about verbosity ([c6f1ab1](https://github.com/desbma/sacad/commit/c6f1ab1b4e02e1bd429019e298850f57ec805972) by desbma)
- Set default log level for third party sources to error ([f5b143d](https://github.com/desbma/sacad/commit/f5b143daf7880013408cd1971cc8f6d5daaf0c44) by desbma)
- Man page & shell completion generation ([1937d6b](https://github.com/desbma/sacad/commit/1937d6becd7119cee60f7bab3d046fa1f3385a9f) by desbma)
- Generate mac binaries on release + use x86_64 instead of amd64 in naming ([1b9cbcc](https://github.com/desbma/sacad/commit/1b9cbcc30374d0dbb8730d3dfde5cf81668dcfd8) by desbma)
- Better support for various artists albums ([424d256](https://github.com/desbma/sacad/commit/424d256b5e4e9afbda2e78162e21b7192183e0fb) by desbma)
- Improve debug logging when having no results ([f523f45](https://github.com/desbma/sacad/commit/f523f453d6d264c2e6f62bd6bc726dd945a4ded0) by desbma)

### <!-- 02 -->🐛 Bug fixes

- Switch to musl toolchain for Linux binaries ([a579e5d](https://github.com/desbma/sacad/commit/a579e5dfe8aa9b114881a4eef41b45749a8b7d70) by desbma)

### <!-- 04 -->📗 Documentation

- README: Mention release binaries ([ce4f398](https://github.com/desbma/sacad/commit/ce4f3982611abb9d9187dbf0bf95188999fe5698) by desbma)

### <!-- 09 -->🤖 Continuous integration

- Remove unneeded permission for cargo audit ([66a29bd](https://github.com/desbma/sacad/commit/66a29bd09bba1ae98db832aedfb9287937569508) by desbma)
- Add msrv check ([6656bdc](https://github.com/desbma/sacad/commit/6656bdc4eafc273afdb932e58abcf62146ebfddc) by desbma)
- Compress windows binaries with 7zip ([e7bee9a](https://github.com/desbma/sacad/commit/e7bee9a10f357ca3bdce78259cfa4221439f27a9) by desbma)
- Update actions versions ([1e30962](https://github.com/desbma/sacad/commit/1e3096261fbc40cd762aaddcc3007da56521b3af) by desbma)
- Build & test on Windows & MacOS ([238d688](https://github.com/desbma/sacad/commit/238d688656f7e925d42d8393bd7764f8f3cf69fd) by desbma)
- Increase release binary compression + add zip in addition to 7zip for Windows ([81529b2](https://github.com/desbma/sacad/commit/81529b2fcc42faa39ef9162c2a738b96e8a5f0df) by desbma)
- Run apt update before any apt install ([fbe2ec9](https://github.com/desbma/sacad/commit/fbe2ec94d270a3a9a8f09100c0a14508ee59e827) by desbma)
- More coherent release archive names and formats ([eda802f](https://github.com/desbma/sacad/commit/eda802f180b93173f3e70baadbb2e2801f922161) by desbma)

### <!-- 10 -->🧰 Miscellaneous tasks

- Update dependencies ([dd4c883](https://github.com/desbma/sacad/commit/dd4c8837a052c882b6304f2f5c0cf5ac431f6d13) by desbma)
- Update AGENTS.md ([211f72f](https://github.com/desbma/sacad/commit/211f72fde5267340c1d9cc2d05a280a9d57f0a3e) by desbma)

______________________________________________________________________

## 3.0.0.b7 - 2026-01-26

### <!-- 01 -->💡 Features

- Support _album tag key ([8246e85](https://github.com/desbma/sacad/commit/8246e8595c6b1e02092dae3be72c17f434da1216) by desbma)
- Add retries for coverartarchive source ([8a61606](https://github.com/desbma/sacad/commit/8a61606d42d3f49d3ed37c8672a6635b04ed5ea6) by desbma)

### <!-- 02 -->🐛 Bug fixes

- ci: Windows zip generation ([f76b930](https://github.com/desbma/sacad/commit/f76b9301e27371e41e1c5ec772df77da386f0ee1) by desbma)

### <!-- 05 -->🧪 Testing

- Add tests for cover embedding ([5479b9e](https://github.com/desbma/sacad/commit/5479b9e6e1dd02fde3609566368245a127b58818) by desbma)
- Add tests for file walker ([0618fcc](https://github.com/desbma/sacad/commit/0618fcc1cbc41fa090b413f01a122cad07dbba9a) by desbma)

______________________________________________________________________

## 3.0.0.b6 - 2026-01-14

### <!-- 02 -->🐛 Bug fixes

- ci: Add missing mingw package, again ([a71bed0](https://github.com/desbma/sacad/commit/a71bed00d44039f6154ceb98ba1479d0f64a18e5) by desbma)
- sacad_r: Fix relative path handling ([0c889e6](https://github.com/desbma/sacad/commit/0c889e62dcbcf089ebc4d607d10dd5044e41d9e7) by desbma)

______________________________________________________________________

## 3.0.0.b5 - 2026-01-12

### <!-- 02 -->🐛 Bug fixes

- ci: Add missing mingw package ([a105431](https://github.com/desbma/sacad/commit/a10543121ac2c0dee7e46ad30ca7b994dcc2df70) by desbma)
- build: Use debloated forked blockhash ([cefe636](https://github.com/desbma/sacad/commit/cefe63602891a5fe479131466223825de6fbd548) by desbma)

______________________________________________________________________

## 3.0.0.b4 - 2026-01-12

### <!-- 05 -->🧪 Testing

- Add cover comparison unit tests ([ce197c3](https://github.com/desbma/sacad/commit/ce197c3a69cc69b2fc189effbe24356ec3335460) by desbma)
- Add Cache::get_or_set unit tests ([dee01a0](https://github.com/desbma/sacad/commit/dee01a0c91b6b36a29ab44ec56699018c79ae7fe) by desbma)
- Add tag unit tests ([ad99cbc](https://github.com/desbma/sacad/commit/ad99cbc82f9ca533d7f56dd3aceebf90fc485890) by desbma)

### <!-- 06 -->🚜 Refactor

- Remove ahash/dhash code superseded by blockhash ([e3defef](https://github.com/desbma/sacad/commit/e3defef42bac30516f016a68b883a099159c870f) by desbma)

### <!-- 09 -->🤖 Continuous integration

- Experimental windows binary generation on release ([272cce3](https://github.com/desbma/sacad/commit/272cce3296969e4b0f8c223b45092a5bb52a0a1c) by desbma)
