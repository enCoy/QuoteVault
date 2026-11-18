/* Quote Vault.app's own program.
 *
 * It runs Python inside itself instead of handing over to the shared Python
 * runtime. That makes macOS treat the running program as "Quote Vault": the
 * Dock shows its name and icon, and the microphone request is made in its
 * name, using the explanation in the app's Info.plist. (When the shared Python
 * runtime was the running program, macOS found no such explanation and
 * refused the microphone without asking.)
 *
 * Built by launcher/build.sh, which fills in the QV_* paths.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    setenv("PYTHONHOME", QV_PYTHONHOME, 1);
    setenv("PYTHONPATH", QV_ROOT ":" QV_SITE, 1);

    /* Python libraries sometimes start helper processes by running "this program" with
     * Python's own options. In that case behave exactly like Python. */
    if (argc > 1 && argv[1][0] == '-' && strncmp(argv[1], "-psn", 4) != 0)
        return Py_BytesMain(argc, argv);

    if (chdir(QV_ROOT) != 0)
        return 1;
    const char *home = getenv("HOME");
    if (home) {
        char log[2048];
        snprintf(log, sizeof log, "%s/Library/Logs/Quote Vault.log", home);
        if (freopen(log, "a", stdout)) setvbuf(stdout, NULL, _IOLBF, 0);
        if (freopen(log, "a", stderr)) setvbuf(stderr, NULL, _IONBF, 0);
    }
    char *args[] = {
        argv[0], "-c",
        "import runpy, site, sys\n"
        "site.addsitedir(r'" QV_SITE "')\n"
        "sys.argv = ['quote-vault', '--window']\n"
        "runpy.run_module('app.serve', run_name='__main__')\n",
        NULL};
    return Py_BytesMain(3, args);
}
