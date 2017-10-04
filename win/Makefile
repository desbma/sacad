# versions
PYTHON_VERSION       := 3.4.4
PYTHON_VERSION_MAJOR := $(word 1,$(subst ., ,${PYTHON_VERSION})).$(word 2,$(subst ., ,${PYTHON_VERSION}))
PYTHON_VERSION_SHORT := $(subst .,,${PYTHON_VERSION_MAJOR})
CXFREEZE_VERSION     := 5.0.2
LXML_VERSION         := 3.8.0

# installers
DOWNLOAD_DIR       ?= dl
PYTHON_INSTALLER   := ${DOWNLOAD_DIR}/python-${PYTHON_VERSION}.msi
CXFREEZE_WHEEL     := ${DOWNLOAD_DIR}/cx_Freeze-${CXFREEZE_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}m-win32.whl
LXML_WHEEL         := ${DOWNLOAD_DIR}/lxml-${LXML_VERSION}-cp${PYTHON_VERSION_SHORT}-none-win32.whl
7ZIP_INSTALLER     := ${DOWNLOAD_DIR}/7z938.msi

# env
CURL     := curl -s -f -L -m 600 --connect-timeout 30 --retry 10 --retry-max-time 5
WINE_DIR := /tmp/$(subst /,_,${CURDIR})/wine
WINE     := mkdir -p $(dir ${WINE_DIR}) && WINEPREFIX=${WINE_DIR} WINEARCH=win32 WINEDEBUG=-all wine

# installed files
PYTHON_INSTALLED   := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/python.exe
CXFREEZE_INSTALLED := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/Scripts/cxfreeze
PIP_INSTALLED      := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/Scripts/pip.exe
LXML_INSTALLED     := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/Lib/site-packages/lxml/__init__.py
7ZIP_INSTALLED     := ${WINE_DIR}/drive_c/7-Zip/7z.sfx

# test
TEST_LIB_DIR := ${WINE_DIR}/drive_c/music


.PHONY: all test test_ut test_freeze fclean clean


all:: sacad_win.7z sacad_win.zip sacad_win.exe

test:: test_ut test_freeze

print-%:
	@echo $*=$($*)


#
# End targets
#

sacad_win.7z: sacad/sacad.exe sacad/sacad_r.exe sacad/LICENSE sacad/readme.txt sacad/python${PYTHON_VERSION_SHORT}.dll sacad/sqlite3.dll
	7z a -t7z -mx9 $@ sacad > /dev/null

sacad_win.zip: sacad/sacad.exe sacad/sacad_r.exe sacad/LICENSE sacad/readme.txt sacad/python${PYTHON_VERSION_SHORT}.dll sacad/sqlite3.dll
	7z a -tzip -mx9 $@ sacad > /dev/null

sacad_win.exe: ${7ZIP_INSTALLED} sacad_win.7z
	cat $^ > $@


#
# Intermediate targets
#

sacad:
	mkdir -p $@

sacad/sacad.exe: sacad ${CXFREEZE_INSTALLED} ${LXML_INSTALLED} .requirements
	cd .. && ${WINE} ${PYTHON_INSTALLED} freeze.py build_exe -b win/sacad 2> /dev/null > /dev/null
	touch $@

sacad/sacad_r.exe: sacad/sacad.exe

sacad/python${PYTHON_VERSION_SHORT}.dll: sacad ${PYTHON_INSTALLED}
	cp $(dir ${PYTHON_INSTALLED})$(notdir $@) $@

sacad/sqlite3.dll: sacad ${PYTHON_INSTALLED}
	cp $(dir ${PYTHON_INSTALLED})DLLs/$(notdir $@) $@

sacad/LICENSE: sacad
	cp ../LICENSE $@

sacad/readme.txt: sacad
	echo 'Get source, help and latest version at: https://github.com/desbma/sacad' > $@


#
# Tests
#

test_ut: ${LXML_INSTALLED} .requirements
	cd .. && ${WINE} ${PYTHON_INSTALLED} setup.py test

test_freeze:: test.jpg ${TEST_LIB_DIR}/test.png

test.jpg: sacad/sacad.exe sacad/python${PYTHON_VERSION_SHORT}.dll sacad/sqlite3.dll
	${WINE} $< "neu" "neu 2" 1000 $@

${TEST_LIB_DIR}:
	mkdir -p $@

${TEST_LIB_DIR}/sample.ogg: ${DOWNLOAD_DIR}/sample.ogg ${TEST_LIB_DIR}
	cp $< $@

${TEST_LIB_DIR}/test.png: ${TEST_LIB_DIR}/sample.ogg sacad/sacad_r.exe sacad/python${PYTHON_VERSION_SHORT}.dll sacad/sqlite3.dll
	${WINE} sacad/sacad_r.exe $(dir $@) 300 $(notdir $@)


#
# Installations
#

.requirements: ${PIP_INSTALLED}
	cd .. && ${WINE} ${PYTHON_INSTALLED} -m pip -qqq install -r requirements.txt
	${WINE} ${PYTHON_INSTALLED} -c "import enum" || ${WINE} ${PYTHON_INSTALLED} -m pip -qqq install enum34
	touch $@

${PYTHON_INSTALLED}: ${PYTHON_INSTALLER}
	${WINE} msiexec /i $< /qb > /dev/null 2> /dev/null
	patch -s ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/Lib/ssl.py < fix-issue26313-python34.patch
	touch $@

${CXFREEZE_INSTALLED}: ${CXFREEZE_WHEEL} ${PIP_INSTALLED} ${PYTHON_INSTALLED}
	${WINE} ${PYTHON_INSTALLED} -m pip -qqq install $<
	touch $@

${PIP_INSTALLED}: ${PYTHON_INSTALLED}
	${WINE} ${PYTHON_INSTALLED} -m pip -qqq install -U pip
	touch $@

${LXML_INSTALLED}: ${LXML_WHEEL} ${PIP_INSTALLED} ${PYTHON_INSTALLED}
	${WINE} ${PYTHON_INSTALLED} -m pip -qqq install $<
	touch $@

${7ZIP_INSTALLED}: ${7ZIP_INSTALLER}
	${WINE} msiexec /i $< /qb INSTALLDIR='c:\7-Zip'
	touch $@


#
# Downloads
#

${PYTHON_INSTALLER}:
	mkdir -p $(dir $@)
	${CURL} https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}.msi > $@

${CXFREEZE_WHEEL}:
	mkdir -p $(dir $@)
	${CURL} https://pypi.python.org/packages/67/87/7b376edca85e4cb24c06d7abde7c4b47c6369b2dadb3856ba8d7b6201106/cx_Freeze-${CXFREEZE_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}m-win32.whl > $@

${LXML_WHEEL}:
	mkdir -p $(dir $@)
	${CURL} https://www.dropbox.com/s/h03crvc5muvim3e/lxml-${LXML_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}m-win32.whl > $@

${7ZIP_INSTALLER}:
	mkdir -p $(dir $@)
	${CURL} http://www.7-zip.org/a/7z938.msi > $@.unckecked
	echo "673377a03f91ff0f7f384794934b767c3389e50d7dc308f7c73f4633121518b3e4af8d33cf282398a710577e12fbb963152591c3e29b1092c79530bb2d8aa882  $@.unckecked" | sha512sum --status -c - && mv $@.unckecked $@

${DOWNLOAD_DIR}/sample.ogg:
	mkdir -p $(dir $@)
	${CURL} http://www.vorbis.com/music/Hydrate-Kenny_Beltrey.ogg > $@


#
# Clean
#

fclean:
	-rm -Rf ${WINE_DIR}
	-rm -Rf sacad .requirements
	-rm -f sacad_win.7z sacad_win.zip sacad_win.exe
	-rm -f test.jpg

clean: fclean
	-rm -Rf ${DOWNLOAD_DIR}
