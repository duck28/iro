# Protocol reference attribution

Iro's Fujifilm preset property identifiers, translation tables, and scan sequence were informed by FilmKit at commit `9e3bbcf858b1f9dc522e90adf7e385554f5969e2`:
https://github.com/eggricesoy/filmkit

The native Windows Portable Devices bridge and Python implementation are project-local implementations. Unknown encodings are preserved and are not converted using guessed defaults. In particular, X-E5 firmware 1.12 grain value 6 is not mapped by the reference tables.

FilmKit's MIT notice is reproduced below for the adapted protocol tables and sequence:

MIT License

Copyright (c) 2026 eggricesoy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The bundled Python runtime license is distributed as `Python-LICENSE.txt` in the Windows application directory. Windows Portable Devices API definitions are supplied by the installed Windows SDK. Iro is independent of Fujifilm.
