# SPDX-License-Identifier: MIT
"""audioairwindows's manifest: it names the C module and freezes no Python.

Include it from your firmware's manifest, beside audiodsp's: the module
builds on audiodsp's audiocore and never alone.
"""

c_module(".")
