#define PY_SSIZE_T_CLEAN
#include <Python.h>

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_speed", NULL, -1, NULL};

PyMODINIT_FUNC PyInit__speed(void) { return PyModule_Create(&module); }
