<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->

# OVMS GPU device mapping

The read-only query used the `openvino_c.dll` bundled in the verified fast-model OVMS installation. Its working directory was `C:\Users\bdgibby\Documents\Codex\2026-09-22\i-w\work\jev-harness-runtime-setup-fast\ovms`. The API calls follow the [OpenVINO 2026 C API reference](https://docs.openvino.ai/2026/api/c_cpp_api/group__ov__core__c__api.html).

Command:

```powershell
@'
import ctypes, os
folder=os.getcwd()
with os.add_dll_directory(folder):
    api=ctypes.CDLL(os.path.join(folder, 'openvino_c.dll'))
    api.ov_core_create.argtypes=[ctypes.POINTER(ctypes.c_void_p)]
    api.ov_core_create.restype=ctypes.c_int
    api.ov_core_get_property.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)]
    api.ov_core_get_property.restype=ctypes.c_int
    api.ov_free.argtypes=[ctypes.c_void_p]
    api.ov_core_free.argtypes=[ctypes.c_void_p]
    core=ctypes.c_void_p()
    rc=api.ov_core_create(ctypes.byref(core))
    print('ov_core_create status=',rc)
    if rc != 0: raise SystemExit(rc)
    try:
        for dev in (b'GPU.0', b'GPU.1'):
            value=ctypes.c_void_p()
            rc=api.ov_core_get_property(core,dev,b'FULL_DEVICE_NAME',ctypes.byref(value))
            print('ov_core_get_property',dev.decode(),'status=',rc, 'full_name=',ctypes.string_at(value).decode('utf-8') if rc == 0 and value.value else '<none>')
            if value.value: api.ov_free(value)
    finally:
        api.ov_core_free(core)
'@ | python -
```

Unedited output (exit 0):

```text
ov_core_create status= 0
ov_core_get_property GPU.0 status= 0 full_name= Intel(R) Graphics (iGPU)
ov_core_get_property GPU.1 status= 0 full_name= Intel(R) Arc(TM) Pro B70 Graphics (dGPU)
```

The running fast OVMS process was queried without changing it. Command:

```powershell
Get-CimInstance Win32_Process -Filter "name='ovms.exe'" | Where-Object { $_.CommandLine -like '*jev-harness-runtime-setup-fast*' } | Select-Object -ExpandProperty CommandLine
```

Unedited output (exit 0):

```text
"C:\Users\bdgibby\Documents\Codex\2026-09-22\i-w\work\jev-harness-runtime-setup-fast\ovms\ovms.exe" --model_path "C:\Users\bdgibby\Documents\Codex\2026-09-22\i-w\work\jev-harness-runtime-setup-fast\model" --model_name qwen25-coder-7b-int4 --task text_generation --target_device GPU.1 --rest_port 8766 --rest_bind_address 127.0.0.1 --port 9002 --grpc_bind_address 127.0.0.1 --log_level INFO
```

The startup log was read with `Get-Content -LiteralPath 'work/jev-harness-runtime-setup-fast/serve-20261004T135524157Z.stdout.log' -TotalCount 15` from the workspace root. Unedited output (exit 0):

```text
[2026-10-04 09:55:24.487][33100][modelmanager][info][servable_loading_queue.cpp:89] Started servable loading queue thread
[2026-10-04 09:55:25.637][41224][modelmanager][info][modelmanager.cpp:252] Available devices for Open VINO: CPU, GPU.0, GPU.1, NPU
[2026-10-04 09:55:25.639][41224][serving][info][capimodule.cpp:40] C-APIModule starting
[2026-10-04 09:55:25.639][41224][serving][info][capimodule.cpp:42] C-APIModule started
[2026-10-04 09:55:25.639][41224][serving][info][grpcservermodule.cpp:106] GRPCServerModule starting
[2026-10-04 09:55:25.640][41224][serving][info][grpcservermodule.cpp:133] Binding gRPC server to address: 127.0.0.1:9002
[2026-10-04 09:55:25.641][41224][serving][info][grpcservermodule.cpp:186] GRPCServerModule started
[2026-10-04 09:55:25.642][41224][serving][info][grpcservermodule.cpp:187] Started gRPC server on port 9002
[2026-10-04 09:55:25.642][41224][serving][info][httpservermodule.cpp:35] HTTPServerModule starting
[2026-10-04 09:55:25.642][41224][serving][info][httpservermodule.cpp:39] Will start 20 REST workers
[2026-10-04 09:55:25.643][38760][serving][info][drogon_http_server.cpp:157] Binding REST server to address: 127.0.0.1:8766
[2026-10-04 09:55:25.708][41224][serving][info][drogon_http_server.cpp:187] REST server listening on port 8766 with 20 unary threads and 20 streaming threads
[2026-10-04 09:55:25.708][41224][serving][info][http_server.cpp:242] API key not provided via --api_key_file or API_KEY environment variable. Authentication will be disabled.
[2026-10-04 09:55:25.709][41224][serving][info][httpservermodule.cpp:52] HTTPServerModule started
[2026-10-04 09:55:25.709][41224][serving][info][httpservermodule.cpp:53] Started REST server at 127.0.0.1:8766
```
