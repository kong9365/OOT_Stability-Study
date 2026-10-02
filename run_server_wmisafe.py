# -*- coding: utf-8 -*-
"""WMI-safe 서버 런처.

Windows WMI 서비스가 hang 상태이면 `import numpy.testing`(scipy 경유)이
`platform.machine()`→`win32_ver`→`_wmi_query`에서 무한 대기해 대시보드가 기동되지 않는다.
여기서 scipy import 전에 platform.uname 결과를 미리 캐시해 WMI 조회를 건너뛴다.
(WMI가 정상이어도 무해. 근본 해결은 재부팅 또는 `Restart-Service Winmgmt -Force`.)

실행:  python run_server_wmisafe.py   (기본 0.0.0.0:8502)
"""
import os
import platform

# WMI 조회 우회 (numpy.testing import hang 방지)
try:
    platform._uname_cache = platform.uname_result("Windows", "localhost", "11", "10.0.26100", "AMD64")
except Exception:
    pass
if hasattr(platform, "_wmi_query"):
    platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(OSError("wmi bypass"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8502"))
    uvicorn.run("dashboard_api:app", host="0.0.0.0", port=port, log_level="info")
