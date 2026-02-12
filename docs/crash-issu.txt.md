-------------------------------------
Translated Report (Full Report Below)
-------------------------------------

Process:               python3.14 [74973]
Path:                  /Users/USER/Documents/*/python
Identifier:            python3.14
Version:               ???
Code Type:             ARM-64 (Native)
Parent Process:        zsh [59137]
Responsible:           Electron [58663]
User ID:               502

Date/Time:             2026-02-12 10:28:33.1982 +0700
OS Version:            macOS 15.7.3 (24G419)
Report Version:        12
Anonymous UUID:        0BD216AE-B2DF-4F4B-8D83-3D2248033012

Sleep/Wake UUID:       91E2667A-4656-418E-8DAF-9B3490A48ED0

Time Awake Since Boot: 940000 seconds
Time Since Wake:       5851 seconds

System Integrity Protection: enabled

Crashed Thread:        0  Dispatch queue: com.apple.main-thread

Exception Type:        EXC_CRASH (SIGABRT)
Exception Codes:       0x0000000000000000, 0x0000000000000000

Termination Reason:    Namespace SIGNAL, Code 6 Abort trap: 6
Terminating Process:   python3.14 [74973]

Application Specific Information:
abort() called


Thread 0 Crashed::  Dispatch queue: com.apple.main-thread
0   libsystem_kernel.dylib        	       0x1a00b6388 __pthread_kill + 8
1   libsystem_pthread.dylib       	       0x1a00ef848 pthread_kill + 296
2   libsystem_c.dylib             	       0x19fff89e4 abort + 124
3   libsystem_malloc.dylib        	       0x19fefc174 malloc_vreport + 892
4   libsystem_malloc.dylib        	       0x19ff27954 malloc_zone_error + 100
5   libsystem_malloc.dylib        	       0x19ff26834 free_tiny_botch + 40
6   libportaudio.dylib            	       0x102cf9dac CloseStream + 648
7   libffi.dylib                  	       0x1b2891050 ffi_call_SYSV + 80
8   libffi.dylib                  	       0x1b2899af0 ffi_call_int + 1220
9   _cffi_backend.cpython-314-darwin.so	       0x105becae8 cdata_call + 1080
10  libpython3.14.dylib           	       0x1014643fc _PyObject_MakeTpCall + 292
11  libpython3.14.dylib           	       0x10159f048 _PyEval_EvalFrameDefault + 20640
12  libpython3.14.dylib           	       0x101599cd0 _PyEval_Vector + 512
13  libpython3.14.dylib           	       0x101467810 method_vectorcall + 444
14  libpyside6.abi3.6.10.dylib    	       0x101cac1a4 callPythonMetaMethodHelper(QList<QByteArray> const&, char const*, void**, _object*) + 368
15  libpyside6.abi3.6.10.dylib    	       0x101cab94c PySide::SignalManager::callPythonMetaMethod(QMetaMethod, void**, _object*) + 84
16  libpyside6.abi3.6.10.dylib    	       0x101cab5d0 SignalManagerPrivate::qtMethodMetacall(QObject*, int, void**) + 824
17  QtCore                        	       0x1025fb33c 0x102510000 + 963388
18  QtWidgets                     	       0x10367f9b0 0x103570000 + 1112496
19  QtWidgets                     	       0x10367f7e8 0x103570000 + 1112040
20  QtWidgets                     	       0x103680834 QAbstractButton::mouseReleaseEvent(QMouseEvent*) + 232
21  QtWidgets.abi3.so             	       0x102edd7d8 QPushButtonWrapper::mouseReleaseEvent(QMouseEvent*) + 132
22  QtWidgets                     	       0x1035cecf0 QWidget::event(QEvent*) + 132
23  QtWidgets.abi3.so             	       0x102edc2bc QPushButtonWrapper::event(QEvent*) + 132
24  QtWidgets                     	       0x103580014 QApplicationPrivate::notify_helper(QObject*, QEvent*) + 332
25  QtWidgets                     	       0x10358213c QApplication::notify(QObject*, QEvent*) + 4820
26  QtWidgets.abi3.so             	       0x1030f4964 QApplicationWrapper::notify(QObject*, QEvent*) + 180
27  QtCore                        	       0x1025a8fa4 QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) + 176
28  QtWidgets                     	       0x10358066c QApplicationPrivate::sendMouseEvent(QWidget*, QMouseEvent*, QWidget*, QWidget*, QWidget**, QPointer<QWidget>&, bool, bool) + 892
29  QtWidgets                     	       0x1035e50f0 0x103570000 + 479472
30  QtWidgets                     	       0x1035e433c 0x103570000 + 475964
31  QtWidgets                     	       0x103580014 QApplicationPrivate::notify_helper(QObject*, QEvent*) + 332
32  QtWidgets                     	       0x10358106c QApplication::notify(QObject*, QEvent*) + 516
33  QtWidgets.abi3.so             	       0x1030f4964 QApplicationWrapper::notify(QObject*, QEvent*) + 180
34  QtCore                        	       0x1025a8fa4 QCoreApplication::sendSpontaneousEvent(QObject*, QEvent*) + 176
35  QtGui                         	       0x101d91db4 QGuiApplicationPrivate::processMouseEvent(QWindowSystemInterfacePrivate::MouseEvent*) + 1968
36  QtGui                         	       0x101df41cc QWindowSystemInterface::sendWindowSystemEvents(QFlags<QEventLoop::ProcessEventsFlag>) + 408
37  libqcocoa.dylib               	       0x1105b8498 0x1105a0000 + 99480
38  CoreFoundation                	       0x1a01daa64 __CFRUNLOOP_IS_CALLING_OUT_TO_A_SOURCE0_PERFORM_FUNCTION__ + 28
39  CoreFoundation                	       0x1a01da9f8 __CFRunLoopDoSource0 + 172
40  CoreFoundation                	       0x1a01da764 __CFRunLoopDoSources0 + 232
41  CoreFoundation                	       0x1a01d93b8 __CFRunLoopRun + 840
42  CoreFoundation                	       0x1a01d89e8 CFRunLoopRunSpecific + 572
43  HIToolbox                     	       0x1abc7927c RunCurrentEventLoopInMode + 324
44  HIToolbox                     	       0x1abc7c31c ReceiveNextEventCommon + 216
45  HIToolbox                     	       0x1abe07484 _BlockUntilNextEventMatchingListInModeWithFilter + 76
46  AppKit                        	       0x1a40f9a34 _DPSNextEvent + 684
47  AppKit                        	       0x1a4a98940 -[NSApplication(NSEventRouting) _nextEventMatchingEventMask:untilDate:inMode:dequeue:] + 688
48  AppKit                        	       0x1a40ecbe4 -[NSApplication run] + 480
49  libqcocoa.dylib               	       0x1105b5d1c 0x1105a0000 + 89372
50  QtCore                        	       0x1025b20f8 QEventLoop::exec(QFlags<QEventLoop::ProcessEventsFlag>) + 588
51  QtCore                        	       0x1025a8b70 QCoreApplication::exec() + 228
52  QtWidgets.abi3.so             	       0x103128e6c Sbk_QApplicationFunc_exec(_object*) + 44
53  libpython3.14.dylib           	       0x101464b0c PyObject_Vectorcall + 88
54  libpython3.14.dylib           	       0x10159f048 _PyEval_EvalFrameDefault + 20640
55  libpython3.14.dylib           	       0x101599a94 PyEval_EvalCode + 416
56  libpython3.14.dylib           	       0x101614638 run_mod + 952
57  libpython3.14.dylib           	       0x101611684 _PyRun_SimpleFileObject + 860
58  libpython3.14.dylib           	       0x101611040 _PyRun_AnyFileObject + 160
59  libpython3.14.dylib           	       0x10163b8d4 pymain_run_file + 336
60  libpython3.14.dylib           	       0x10163b1a0 Py_RunMain + 1572
61  libpython3.14.dylib           	       0x10163b418 pymain_main + 320
62  libpython3.14.dylib           	       0x10163b4b8 Py_BytesMain + 40
63  dyld                          	       0x19fd4eb98 start + 6076

Thread 1:: caulk.messenger.shared:17
0   libsystem_kernel.dylib        	       0x1a00adbb0 semaphore_wait_trap + 8
1   caulk                         	       0x1ab760cc8 caulk::semaphore::timed_wait(double) + 224
2   caulk                         	       0x1ab760b70 caulk::concurrent::details::worker_thread::run() + 32
3   caulk                         	       0x1ab760844 void* caulk::thread_proxy<std::__1::tuple<caulk::thread::attributes, void (caulk::concurrent::details::worker_thread::*)(), std::__1::tuple<caulk::concurrent::details::worker_thread*>>>(void*) + 96
4   libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
5   libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 2:: caulk.messenger.shared:high
0   libsystem_kernel.dylib        	       0x1a00adbb0 semaphore_wait_trap + 8
1   caulk                         	       0x1ab760cc8 caulk::semaphore::timed_wait(double) + 224
2   caulk                         	       0x1ab760b70 caulk::concurrent::details::worker_thread::run() + 32
3   caulk                         	       0x1ab760844 void* caulk::thread_proxy<std::__1::tuple<caulk::thread::attributes, void (caulk::concurrent::details::worker_thread::*)(), std::__1::tuple<caulk::concurrent::details::worker_thread*>>>(void*) + 96
4   libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
5   libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 3:
0   libsystem_pthread.dylib       	       0x1a00eab6c start_wqthread + 0

Thread 4:: com.apple.NSEventThread
0   libsystem_kernel.dylib        	       0x1a00adc34 mach_msg2_trap + 8
1   libsystem_kernel.dylib        	       0x1a00c03a0 mach_msg2_internal + 76
2   libsystem_kernel.dylib        	       0x1a00b6764 mach_msg_overwrite + 484
3   libsystem_kernel.dylib        	       0x1a00adfa8 mach_msg + 24
4   CoreFoundation                	       0x1a01dac0c __CFRunLoopServiceMachPort + 160
5   CoreFoundation                	       0x1a01d9528 __CFRunLoopRun + 1208
6   CoreFoundation                	       0x1a01d89e8 CFRunLoopRunSpecific + 572
7   AppKit                        	       0x1a421d78c _NSEventThread + 140
8   libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
9   libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 5:
0   libsystem_pthread.dylib       	       0x1a00eab6c start_wqthread + 0

Thread 6:
0   libsystem_pthread.dylib       	       0x1a00eab6c start_wqthread + 0

Thread 7:: Thread (pooled)
0   libsystem_kernel.dylib        	       0x1a00b13cc __psynch_cvwait + 8
1   libsystem_pthread.dylib       	       0x1a00f009c _pthread_cond_wait + 984
2   QtCore                        	       0x1027478d8 0x102510000 + 2324696
3   QtCore                        	       0x102747768 QWaitCondition::wait(QMutex*, QDeadlineTimer) + 108
4   QtCore                        	       0x1026a3a64 0x102510000 + 1653348
5   QtCore                        	       0x10273edec 0x102510000 + 2289132
6   libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
7   libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 8:: Thread (pooled)
0   libsystem_kernel.dylib        	       0x1a00b13cc __psynch_cvwait + 8
1   libsystem_pthread.dylib       	       0x1a00f009c _pthread_cond_wait + 984
2   QtCore                        	       0x1027478d8 0x102510000 + 2324696
3   QtCore                        	       0x102747768 QWaitCondition::wait(QMutex*, QDeadlineTimer) + 108
4   QtCore                        	       0x1026a3a64 0x102510000 + 1653348
5   QtCore                        	       0x10273edec 0x102510000 + 2289132
6   libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
7   libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 9:: SonioxWorker
0   libsystem_kernel.dylib        	       0x1a00b3d04 kevent + 8
1   select.cpython-314-darwin.so  	       0x102cde588 select_kqueue_control + 756
2   libpython3.14.dylib           	       0x1015a437c _PyEval_EvalFrameDefault + 41940
3   libpython3.14.dylib           	       0x101599cd0 _PyEval_Vector + 512
4   libpython3.14.dylib           	       0x101467790 method_vectorcall + 316
5   QtCore.abi3.so                	       0x106f17254 QThreadWrapper::sbk_o_run(char const*, char const*, Shiboken::GilState&, Shiboken::AutoDecRef const&) + 108
6   QtCore.abi3.so                	       0x106f17174 QThreadWrapper::run() + 112
7   QtCore                        	       0x10273edec 0x102510000 + 2289132
8   libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
9   libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 10:: RecorderWorker
0   libsystem_kernel.dylib        	       0x1a00b13cc __psynch_cvwait + 8
1   libsystem_pthread.dylib       	       0x1a00f00c8 _pthread_cond_wait + 1028
2   libpython3.14.dylib           	       0x101605868 _PySemaphore_Wait + 232
3   libpython3.14.dylib           	       0x101605a70 _PyParkingLot_Park + 420
4   libpython3.14.dylib           	       0x1015fe6c8 _PyMutex_LockTimed + 456
5   libpython3.14.dylib           	       0x10169a15c lock_PyThread_acquire_lock + 60
6   libpython3.14.dylib           	       0x101471ae4 method_vectorcall_VARARGS_KEYWORDS + 236
7   libpython3.14.dylib           	       0x101464b0c PyObject_Vectorcall + 88
8   libpython3.14.dylib           	       0x1015a2424 _PyEval_EvalFrameDefault + 33916
9   libpython3.14.dylib           	       0x101599cd0 _PyEval_Vector + 512
10  libpython3.14.dylib           	       0x101467790 method_vectorcall + 316
11  QtCore.abi3.so                	       0x106f17254 QThreadWrapper::sbk_o_run(char const*, char const*, Shiboken::GilState&, Shiboken::AutoDecRef const&) + 108
12  QtCore.abi3.so                	       0x106f17174 QThreadWrapper::run() + 112
13  QtCore                        	       0x10273edec 0x102510000 + 2289132
14  libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
15  libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 11:: asyncio_0
0   libsystem_kernel.dylib        	       0x1a00b13cc __psynch_cvwait + 8
1   libsystem_pthread.dylib       	       0x1a00f009c _pthread_cond_wait + 984
2   libpython3.14.dylib           	       0x101605878 _PySemaphore_Wait + 248
3   libpython3.14.dylib           	       0x101605a70 _PyParkingLot_Park + 420
4   _queue.cpython-314-darwin.so  	       0x105bc8da8 _queue_SimpleQueue_get + 528
5   libpython3.14.dylib           	       0x101464b0c PyObject_Vectorcall + 88
6   libpython3.14.dylib           	       0x1015a1f84 _PyEval_EvalFrameDefault + 32732
7   libpython3.14.dylib           	       0x101599cd0 _PyEval_Vector + 512
8   libpython3.14.dylib           	       0x101467790 method_vectorcall + 316
9   libpython3.14.dylib           	       0x1015c5e9c context_run + 136
10  libpython3.14.dylib           	       0x101464b0c PyObject_Vectorcall + 88
11  libpython3.14.dylib           	       0x10159f048 _PyEval_EvalFrameDefault + 20640
12  libpython3.14.dylib           	       0x101599cd0 _PyEval_Vector + 512
13  libpython3.14.dylib           	       0x101467790 method_vectorcall + 316
14  libpython3.14.dylib           	       0x10169914c thread_run + 128
15  libpython3.14.dylib           	       0x101629890 pythread_wrapper + 28
16  libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
17  libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8

Thread 12:: caulk::deferred_logger
0   libsystem_kernel.dylib        	       0x1a00adbb0 semaphore_wait_trap + 8
1   caulk                         	       0x1ab760cc8 caulk::semaphore::timed_wait(double) + 224
2   caulk                         	       0x1ab760b70 caulk::concurrent::details::worker_thread::run() + 32
3   caulk                         	       0x1ab760844 void* caulk::thread_proxy<std::__1::tuple<caulk::thread::attributes, void (caulk::concurrent::details::worker_thread::*)(), std::__1::tuple<caulk::concurrent::details::worker_thread*>>>(void*) + 96
4   libsystem_pthread.dylib       	       0x1a00efbc8 _pthread_start + 136
5   libsystem_pthread.dylib       	       0x1a00eab80 thread_start + 8


Thread 0 crashed with ARM Thread State (64-bit):
    x0: 0x0000000000000000   x1: 0x0000000000000000   x2: 0x0000000000000000   x3: 0x0000000000000000
    x4: 0x0000000000000073   x5: 0x000000000000002e   x6: 0x0000000000000001   x7: 0x0000000000000b10
    x8: 0xf806c1d02d0112c4   x9: 0xf806c1d223097084  x10: 0x000000000000000a  x11: 0x0000000000000000
   x12: 0x0000000000000037  x13: 0x0000000000200000  x14: 0x9e3779b97f4a7c55  x15: 0x00000000802090ff
   x16: 0x0000000000000148  x17: 0x000000020f0dd548  x18: 0x0000000000000000  x19: 0x0000000000000006
   x20: 0x0000000000000103  x21: 0x000000020e086320  x22: 0x000000019ff33aea  x23: 0x000000016f34aac0
   x24: 0x0000000000000000  x25: 0x0000000000000000  x26: 0x000000016f34f264  x27: 0x000000020e086240
   x28: 0x00000001237ef200   fp: 0x000000016f34a410   lr: 0x00000001a00ef848
    sp: 0x000000016f34a3f0   pc: 0x00000001a00b6388 cpsr: 0x40000000
   far: 0x0000000000000000  esr: 0x56000080  Address size fault

Binary Images:
       0x100ab0000 -        0x100ab3fff python (*) <1d6159a5-3515-387f-8801-9f7709588294> /Users/USER/Documents/*/python
       0x101414000 -        0x1017bffff libpython3.14.dylib (*) <a438413d-ec7c-3071-a037-09f3bb66e4c2> /Users/USER/*/libpython3.14.dylib
       0x100af8000 -        0x100b1ffff libintl.8.dylib (*) <85a5d333-79ed-39ec-b780-3629376eeaa3> /opt/homebrew/*/libintl.8.dylib
       0x100d5c000 -        0x100d5ffff grp.cpython-314-darwin.so (*) <ffded3a4-2d30-339b-a788-5b60c5bbd700> /Users/USER/*/grp.cpython-314-darwin.so
       0x100d6c000 -        0x100d6ffff fcntl.cpython-314-darwin.so (*) <0d45bc51-bcf3-3031-bf75-e45f372aa4d2> /Users/USER/*/fcntl.cpython-314-darwin.so
       0x100d7c000 -        0x100d7ffff binascii.cpython-314-darwin.so (*) <a8690b96-3375-36fc-8f37-362b9bfb81f1> /Users/USER/*/binascii.cpython-314-darwin.so
       0x100da0000 -        0x100da7fff zlib.cpython-314-darwin.so (*) <400d4d6b-dabb-3d26-bece-c6553c319a4d> /Users/USER/*/zlib.cpython-314-darwin.so
       0x100d8c000 -        0x100d8ffff _bz2.cpython-314-darwin.so (*) <a71a3461-9265-3717-8a8c-89463e53743a> /Users/USER/*/_bz2.cpython-314-darwin.so
       0x100dc8000 -        0x100dcffff _lzma.cpython-314-darwin.so (*) <20d61fed-8edc-325a-81a5-70968f0ee050> /Users/USER/*/_lzma.cpython-314-darwin.so
       0x101074000 -        0x101093fff liblzma.5.dylib (*) <bc9cf488-263b-371e-a310-197d38b4b182> /opt/homebrew/*/liblzma.5.dylib
       0x100df4000 -        0x100dfbfff _zstd.cpython-314-darwin.so (*) <786f90bd-1baa-3f6a-847a-1662183d7942> /Users/USER/*/_zstd.cpython-314-darwin.so
       0x101144000 -        0x1011cbfff libzstd.1.5.7.dylib (*) <f85645bb-8df7-325e-b22d-ff4b265f9465> /opt/homebrew/*/libzstd.1.5.7.dylib
       0x1010a4000 -        0x1010abfff _struct.cpython-314-darwin.so (*) <4df1660e-75b1-32de-a07a-1d231ee2f252> /Users/USER/*/_struct.cpython-314-darwin.so
       0x1010d8000 -        0x1010e3fff math.cpython-314-darwin.so (*) <6e1fca02-37ed-37c7-8e3a-4fe0a4cce326> /Users/USER/*/math.cpython-314-darwin.so
       0x100db4000 -        0x100db7fff _bisect.cpython-314-darwin.so (*) <1eacc435-223a-35b2-8d0c-041b645a4495> /Users/USER/*/_bisect.cpython-314-darwin.so
       0x100ddc000 -        0x100ddffff _random.cpython-314-darwin.so (*) <ab21f48a-4eda-3364-b3e3-bed867e3b7ed> /Users/USER/*/_random.cpython-314-darwin.so
       0x100d4c000 -        0x100d4ffff Shiboken.abi3.so (*) <34590199-3ce2-32b1-aa23-b4a50138a445> /Users/USER/Documents/*/Shiboken.abi3.so
       0x101b1c000 -        0x101b6bfff libshiboken6.abi3.6.10.dylib (*) <f0b78160-24ab-3c2d-bccc-4ef944f40d30> /Users/USER/Documents/*/libshiboken6.abi3.6.10.dylib
       0x102d28000 -        0x103243fff QtWidgets.abi3.so (*) <188a1c2d-f44f-3e57-bd21-a37a7a840d28> /Users/USER/Documents/*/QtWidgets.abi3.so
       0x101c98000 -        0x101cd7fff libpyside6.abi3.6.10.dylib (*) <1da89093-9eca-3280-a410-df22a1865bbd> /Users/USER/Documents/*/libpyside6.abi3.6.10.dylib
       0x103570000 -        0x1039dbfff org.qt-project.QtWidgets (6.10) <029543bf-5fc1-3a0c-ade7-edba0cf3d8b1> /Users/USER/Documents/*/QtWidgets.framework/Versions/A/QtWidgets
       0x101d04000 -        0x1023c7fff org.qt-project.QtGui (6.10) <3fa37de7-ceac-3c91-9317-791e19111d2a> /Users/USER/Documents/*/QtGui.framework/Versions/A/QtGui
       0x102510000 -        0x1029cffff org.qt-project.QtCore (6.10) <4a7a0348-b410-3e23-8373-53f6876eb7f4> /Users/USER/Documents/*/QtCore.framework/Versions/A/QtCore
       0x101a24000 -        0x101aabfff org.qt-project.QtDBus (6.10) <46e5cebb-3051-35c6-aa1e-6f530f243273> /Users/USER/Documents/*/QtDBus.framework/Versions/A/QtDBus
       0x101acc000 -        0x101aebfff com.apple.security.csparser (3.0) <58f759bc-cd52-3491-8dd0-7f34f32cfc35> /System/Library/Frameworks/Security.framework/Versions/A/PlugIns/csparser.bundle/Contents/MacOS/csparser
       0x106830000 -        0x106c1ffff QtGui.abi3.so (*) <19d1f0df-5853-3f4e-92f0-cf3d8ba3aeb4> /Users/USER/Documents/*/QtGui.abi3.so
       0x106e84000 -        0x1071d7fff QtCore.abi3.so (*) <62750a98-bc70-38bc-96d4-b518d7fefded> /Users/USER/Documents/*/QtCore.abi3.so
       0x102cb0000 -        0x102cc7fff _ctypes.cpython-314-darwin.so (*) <8d37b005-a428-31e0-a3b5-c812211b3711> /Users/USER/*/_ctypes.cpython-314-darwin.so
       0x101404000 -        0x10140bfff libffi-trampolines.dylib (*) <42996791-868d-3ae4-a498-6aaeae8d9643> /usr/lib/libffi-trampolines.dylib
       0x101b08000 -        0x101b0bfff _posixsubprocess.cpython-314-darwin.so (*) <493605be-27c1-3c3f-b708-41915a8fdc10> /Users/USER/*/_posixsubprocess.cpython-314-darwin.so
       0x102cdc000 -        0x102ce3fff select.cpython-314-darwin.so (*) <9af991d1-ff78-3372-b7b9-084bcfadee45> /Users/USER/*/select.cpython-314-darwin.so
       0x105be0000 -        0x105c03fff _cffi_backend.cpython-314-darwin.so (*) <0f4530a9-be00-3233-93ca-f2b0eacda2cc> /Users/USER/Documents/*/_cffi_backend.cpython-314-darwin.so
       0x102cf0000 -        0x102cfffff libportaudio.dylib (*) <55cca076-e47e-384c-8f52-4c38b10bf10b> /Users/USER/Documents/*/libportaudio.dylib
       0x102d10000 -        0x102d17fff _interpreters.cpython-314-darwin.so (*) <7d80db41-fb37-3f5d-a3b3-41e028aa7229> /Users/USER/*/_interpreters.cpython-314-darwin.so
       0x105ba4000 -        0x105ba7fff _heapq.cpython-314-darwin.so (*) <f6ea58f1-baf1-328c-903a-71f2f71481fd> /Users/USER/*/_heapq.cpython-314-darwin.so
       0x105c1c000 -        0x105c2bfff _socket.cpython-314-darwin.so (*) <c697831c-10cb-3907-8b82-82a7aa557da3> /Users/USER/*/_socket.cpython-314-darwin.so
       0x105c70000 -        0x105c8bfff _ssl.cpython-314-darwin.so (*) <df4ada91-f9dc-3e8c-88c0-aad21fc95e7e> /Users/USER/*/_ssl.cpython-314-darwin.so
       0x1062e0000 -        0x106373fff libssl.3.dylib (*) <810d99f1-2504-3db7-9357-4bce9d47fc76> /opt/homebrew/*/libssl.3.dylib
       0x1078a0000 -        0x107bdffff libcrypto.3.dylib (*) <efba4c7a-a8ab-3429-8076-3bf9f22bd40b> /opt/homebrew/*/libcrypto.3.dylib
       0x105c3c000 -        0x105c47fff _asyncio.cpython-314-darwin.so (*) <bb9c3618-9b56-3ef4-b5ff-7aa8698d92e2> /Users/USER/*/_asyncio.cpython-314-darwin.so
       0x105bb4000 -        0x105bbbfff _json.cpython-314-darwin.so (*) <f62ae53d-f8d9-3f9c-b264-9151df11df46> /Users/USER/*/_json.cpython-314-darwin.so
       0x105bc8000 -        0x105bcbfff _queue.cpython-314-darwin.so (*) <94f00468-02df-3eb3-b12c-b6df6020ff1c> /Users/USER/*/_queue.cpython-314-darwin.so
       0x110000000 -        0x1102effff _multiarray_umath.cpython-314-darwin.so (*) <312efc40-1db2-3e84-8a23-06893a3f3b70> /Users/USER/Documents/*/_multiarray_umath.cpython-314-darwin.so
       0x105ccc000 -        0x105ce3fff _pickle.cpython-314-darwin.so (*) <37fc8ec5-ec68-3803-91c3-aa2ebaf98734> /Users/USER/*/_pickle.cpython-314-darwin.so
       0x106200000 -        0x106217fff _umath_linalg.cpython-314-darwin.so (*) <db11f106-e295-3c29-90ca-af4b71a96d77> /Users/USER/Documents/*/_umath_linalg.cpython-314-darwin.so
       0x11068c000 -        0x1108fbfff libsndfile_arm64.dylib (*) <468ad400-0f51-3371-9d86-e665fb5bc4fe> /Users/USER/Documents/*/libsndfile_arm64.dylib
       0x111900000 -        0x111cb7fff _pydantic_core.cpython-314-darwin.so (*) <f2474c21-5f58-3f72-b3b2-c733df05d534> /Users/USER/Documents/*/_pydantic_core.cpython-314-darwin.so
       0x106260000 -        0x106283fff _decimal.cpython-314-darwin.so (*) <60f7fd79-2332-3241-8fc1-e9fab3da0503> /Users/USER/*/_decimal.cpython-314-darwin.so
       0x106298000 -        0x1062b3fff libmpdec.4.0.1.dylib (*) <52d16117-fcf0-3704-984f-ce4454923a78> /opt/homebrew/*/libmpdec.4.0.1.dylib
       0x105c58000 -        0x105c5ffff _zoneinfo.cpython-314-darwin.so (*) <26d26070-26b9-3392-9360-393bba842f54> /Users/USER/*/_zoneinfo.cpython-314-darwin.so
       0x105ca4000 -        0x105ca7fff _uuid.cpython-314-darwin.so (*) <ff036484-33d3-30ad-bf35-35d3a9ac47fe> /Users/USER/*/_uuid.cpython-314-darwin.so
       0x106228000 -        0x10622ffff _hashlib.cpython-314-darwin.so (*) <fbfa0062-902c-329d-9ae8-b3c402a61713> /Users/USER/*/_hashlib.cpython-314-darwin.so
       0x106240000 -        0x106247fff _blake2.cpython-314-darwin.so (*) <f9b5791a-c5d7-3236-962b-92f163eabac9> /Users/USER/*/_blake2.cpython-314-darwin.so
       0x105cb4000 -        0x105cb7fff _scproxy.cpython-314-darwin.so (*) <ad25c96b-8cb5-3154-a285-89df31644ad6> /Users/USER/*/_scproxy.cpython-314-darwin.so
       0x110aa8000 -        0x110b5bfff unicodedata.cpython-314-darwin.so (*) <d0b139a8-9789-366a-bb07-be4c199acf6e> /Users/USER/*/unicodedata.cpython-314-darwin.so
       0x106800000 -        0x10681bfff _hmac.cpython-314-darwin.so (*) <ad48623a-0fb0-3adc-a4a9-68386517a123> /Users/USER/*/_hmac.cpython-314-darwin.so
       0x1062c8000 -        0x1062cbfff md.cpython-314-darwin.so (*) <a6bcc18a-d077-3fcc-afac-145c8986c980> /Users/USER/Documents/*/md.cpython-314-darwin.so
       0x1064c0000 -        0x1064e7fff md__mypyc.cpython-314-darwin.so (*) <c4cdb4a2-83b4-3291-9c30-7e76c275b2a8> /Users/USER/Documents/*/md__mypyc.cpython-314-darwin.so
       0x107810000 -        0x107817fff _multibytecodec.cpython-314-darwin.so (*) <2fe821a4-167c-3afe-aa4f-33dc00c6a7e7> /Users/USER/*/_multibytecodec.cpython-314-darwin.so
       0x124670000 -        0x124dbbfff _rust.abi3.so (*) <6f7210a5-b0c3-3ba4-9724-763319638abb> /Users/USER/Documents/*/_rust.abi3.so
       0x1105a0000 -        0x11064bfff libqcocoa.dylib (*) <3dd57985-5eac-307d-a26f-1a4f2a8ce5dd> /Users/USER/Documents/*/libqcocoa.dylib
       0x111e84000 -        0x111e8ffff libobjc-trampolines.dylib (*) <9a87f143-aa9d-3c46-b2e8-b3fb9215e33e> /usr/lib/libobjc-trampolines.dylib
       0x111e98000 -        0x111ebbfff libqmacstyle.dylib (*) <3124ba49-4f2c-36d2-9fd9-f382a264172e> /Users/USER/Documents/*/libqmacstyle.dylib
       0x141d58000 -        0x14248bfff com.apple.AGXMetalG16G-B0 (329.2) <0e26b74f-2e37-3338-bd21-410cf4b9d199> /System/Library/Extensions/AGXMetalG16G_B0.bundle/Contents/MacOS/AGXMetalG16G_B0
       0x143e6c000 -        0x143e77fff _psutil_osx.abi3.so (*) <9f38d1a0-1af2-3062-9683-0e0d0af4a252> /Users/USER/Documents/*/_psutil_osx.abi3.so
       0x147b64000 -        0x147c9ffff com.apple.audio.units.Components (1.14) <917d6875-01f4-33f6-a9f0-bc16669a67bb> /System/Library/Components/CoreAudio.component/Contents/MacOS/CoreAudio
       0x1a00ad000 -        0x1a00e8663 libsystem_kernel.dylib (*) <1d4ffd44-8926-3746-924e-deef5b777588> /usr/lib/system/libsystem_kernel.dylib
       0x1a00e9000 -        0x1a00f5a77 libsystem_pthread.dylib (*) <022dc315-cf35-38da-939e-03800b5beff2> /usr/lib/system/libsystem_pthread.dylib
       0x19ff80000 -        0x1a00011f7 libsystem_c.dylib (*) <e098cb59-2c56-395c-ade1-6ef590e61199> /usr/lib/system/libsystem_c.dylib
       0x19feee000 -        0x19ff3506f libsystem_malloc.dylib (*) <3ce1e59c-91c8-3259-93d8-7ded66842979> /usr/lib/system/libsystem_malloc.dylib
       0x1b2889000 -        0x1b289a7af libffi.dylib (*) <8693ce95-5faf-347d-83ae-6471bd0838fd> /usr/lib/libffi.dylib
       0x1a015e000 -        0x1a069cfff com.apple.CoreFoundation (6.9) <37cebb20-0448-392c-9f01-f5bd87eb295e> /System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation
       0x1abbb6000 -        0x1abebcfdf com.apple.HIToolbox (2.1.1) <7537dc6d-3280-335e-9259-ed5d308d29ec> /System/Library/Frameworks/Carbon.framework/Versions/A/Frameworks/HIToolbox.framework/Versions/A/HIToolbox
       0x1a40bf000 -        0x1a554fcff com.apple.AppKit (6.9) <00452387-9d4c-397a-a17d-cd14bb6ce9b4> /System/Library/Frameworks/AppKit.framework/Versions/C/AppKit
       0x19fd48000 -        0x19fde357b dyld (*) <e4e5cd37-5339-3136-b2c5-0c80f0720c26> /usr/lib/dyld
               0x0 - 0xffffffffffffffff ??? (*) <00000000-0000-0000-0000-000000000000> ???
       0x1ab75f000 -        0x1ab786ddf com.apple.audio.caulk (1.0) <fa67137d-9735-3dce-8716-ab20f8cd6e24> /System/Library/PrivateFrameworks/caulk.framework/Versions/A/caulk

External Modification Summary:
  Calls made by other processes targeting this process:
    task_for_pid: 0
    thread_create: 0
    thread_set_state: 0
  Calls made by this process:
    task_for_pid: 0
    thread_create: 0
    thread_set_state: 0
  Calls made by all processes on this machine:
    task_for_pid: 0
    thread_create: 0
    thread_set_state: 0

