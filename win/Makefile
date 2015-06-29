# versions
PYTHON_VERSION       := 3.3.5
PYTHON_VERSION_MAJOR := $(word 1,$(subst ., ,${PYTHON_VERSION})).$(word 2,$(subst ., ,${PYTHON_VERSION}))
PYTHON_VERSION_SHORT := $(subst .,,${PYTHON_VERSION_MAJOR})
CXFREEZE_VERSION     := 4.3.3
LXML_VERSION         := 3.4.3

# installers
PYTHON_INSTALLER   := python-${PYTHON_VERSION}.msi
CXFREEZE_INSTALLER := cx_Freeze-${CXFREEZE_VERSION}.win32-py${PYTHON_VERSION_MAJOR}.msi
PIP_INSTALLER      := get-pip.py
LXML_INSTALLER     := lxml-${LXML_VERSION}-cp${PYTHON_VERSION_SHORT}-none-win32.whl
7ZIP_INSTALLER     := 7z938.msi

# env
CURL     := curl -s -f -L -m 60
WINE_DIR := ${CURDIR}/wine
WINE     := WINEPREFIX=${WINE_DIR} WINEARCH=win32 wine

# installed files
PYTHON_INSTALLED   := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/python.exe
CXFREEZE_INSTALLED := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/Scripts/cxfreeze
PIP_INSTALLED      := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/Scripts/pip.exe
LXML_INSTALLED     := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/Lib/site-packages/lxml/__init__.py
7ZIP_INSTALLED     := ${WINE_DIR}/drive_c/7-Zip/7z.sfx


.PHONY: all test


all:: sacad_win.7z sacad_win.zip sacad_win.exe

test:: test.jpg

print-%:
	@echo $*=$($*)

sacad_win.7z: sacad/sacad.exe sacad/LICENSE sacad/readme.txt sacad/python${PYTHON_VERSION_SHORT}.dll sacad/sqlite3.dll
	7z a -t7z -mx9 $@ sacad > /dev/null

sacad_win.zip: sacad/sacad.exe sacad/LICENSE sacad/readme.txt sacad/python${PYTHON_VERSION_SHORT}.dll sacad/sqlite3.dll
	7z a -tzip -mx9 $@ sacad > /dev/null

sacad_win.exe: ${7ZIP_INSTALLED} sacad_win.7z
	cat $^ > $@

test.jpg: sacad/sacad.exe
	cd $(dir $<) && ${WINE} $(notdir $<) "neu" "neu 2" 1000 ../$@

sacad/sacad.exe: ${CXFREEZE_INSTALLED} ${LXML_INSTALLED} .requirements
	mkdir -p $(dir $@)
	cd .. && ${WINE} ${PYTHON_INSTALLED} freeze.py build_exe -b win/sacad 2> /dev/null > /dev/null
	touch $@

sacad/python${PYTHON_VERSION_SHORT}.dll: ${PYTHON_INSTALLED}
	mkdir -p $(dir $@)
	cp $(dir ${PYTHON_INSTALLED})$(notdir $@) $@

sacad/sqlite3.dll: ${PYTHON_INSTALLED}
	mkdir -p $(dir $@)
	cp $(dir ${PYTHON_INSTALLED})DLLs/$(notdir $@) $@

sacad/LICENSE:
	mkdir -p $(dir $@)
	${CURL} https://www.mozilla.org/MPL/2.0/index.txt > $@

sacad/readme.txt:
	mkdir -p $(dir $@)
	echo 'Get source, help and latest version at: https://github.com/desbma/sacad' > $@

.requirements: ${PIP_INSTALLED}
	cd .. && ${WINE} ${PYTHON_INSTALLED} -m pip install -r requirements.txt 2> /dev/null > /dev/null
	touch $@

${PYTHON_INSTALLED}: ${PYTHON_INSTALLER}
	${WINE} msiexec /i $< /qb 2> /dev/null
	touch $@

${CXFREEZE_INSTALLED}: ${CXFREEZE_INSTALLER} ${PYTHON_INSTALLED}
	${WINE} msiexec /i $< /qb 2> /dev/null
	touch $@

${PIP_INSTALLED}: ${PIP_INSTALLER} ${PYTHON_INSTALLED}
	${WINE} ${PYTHON_INSTALLED} $< 2> /dev/null > /dev/null
	touch $@

${LXML_INSTALLED}: ${LXML_INSTALLER} ${PIP_INSTALLED} ${PYTHON_INSTALLED}
	${WINE} ${PYTHON_INSTALLED} -m pip install wheel 2> /dev/null > /dev/null
	${WINE} ${PYTHON_INSTALLED} -m pip install $< 2> /dev/null > /dev/null
	touch $@

${7ZIP_INSTALLED}: ${7ZIP_INSTALLER}
	${WINE} msiexec /i $< /qb INSTALLDIR='c:\7-Zip' 2> /dev/null
	touch $@

${PYTHON_INSTALLER}:
	${CURL} http://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}.msi > $@

${CXFREEZE_INSTALLER}:
	${CURL} http://sourceforge.net/projects/cx-freeze/files/${CXFREEZE_VERSION}/cx_Freeze-${CXFREEZE_VERSION}.win32-py${PYTHON_VERSION_MAJOR}.msi > $@

${PIP_INSTALLER}:
	${CURL} https://bootstrap.pypa.io/get-pip.py > $@

${LXML_INSTALLER}:
	${CURL} https://dl.dropboxusercontent.com/u/70127955/lxml-${LXML_VERSION}-cp${PYTHON_VERSION_SHORT}-none-win32.whl > $@

${7ZIP_INSTALLER}:
	${CURL} http://www.7-zip.org/a/7z938.msi > $@

clean:
	@-rm -Rvf ${WINE_DIR}
	@-rm -vf ${PYTHON_INSTALLER} ${CXFREEZE_INSTALLER} ${PIP_INSTALLER} ${LXML_INSTALLER} ${7ZIP_INSTALLER}
	@-rm -Rvf sacad .requirements
	@-rm -Rvf 7z920_extra.7z 7z920_extra
	@-rm -vf sacad_win.7z sacad_win.zip sacad_win.exe
	@-rm -vf test.jpg
