WINEARCH ?= win32

# versions
PYTHON_VERSION       := 3.8.10
PYTHON_VERSION_MAJOR := $(word 1,$(subst ., ,${PYTHON_VERSION})).$(word 2,$(subst ., ,${PYTHON_VERSION}))
PYTHON_VERSION_SHORT := $(subst .,,${PYTHON_VERSION_MAJOR})
CXFREEZE_VERSION     := 6.10
LXML_VERSION         := 4.7.1
BITARRAY_VERSION     := 2.3.5

# installers & packages
DOWNLOAD_DIR                    ?= dl
PYTHON_EMBEDDABLE_ARCHIVE-win32 := ${DOWNLOAD_DIR}/python-${PYTHON_VERSION}-embed-win32.zip
PYTHON_EMBEDDABLE_ARCHIVE-win64 := ${DOWNLOAD_DIR}/python-${PYTHON_VERSION}-embed-amd64.zip
PYTHON_EMBEDDABLE_ARCHIVE       := ${PYTHON_EMBEDDABLE_ARCHIVE-${WINEARCH}}
GET_PIP                         := ${DOWNLOAD_DIR}/get-pip.py
CXFREEZE_WHEEL-win32            := ${DOWNLOAD_DIR}/cx_Freeze-${CXFREEZE_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}-${WINEARCH}.whl
CXFREEZE_WHEEL-win64            := ${DOWNLOAD_DIR}/cx_Freeze-${CXFREEZE_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}-win_amd64.whl
CXFREEZE_WHEEL                  := ${CXFREEZE_WHEEL-${WINEARCH}}
LXML_WHEEL-win32                := ${DOWNLOAD_DIR}/lxml-${LXML_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}-${WINEARCH}.whl
LXML_WHEEL-win64                := ${DOWNLOAD_DIR}/lxml-${LXML_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}-win_amd64.whl
LXML_WHEEL                      := ${LXML_WHEEL-${WINEARCH}}
BITARRAY_WHEEL-win32            := ${DOWNLOAD_DIR}/bitarray-${BITARRAY_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}-${WINEARCH}.whl
BITARRAY_WHEEL-win64            := ${DOWNLOAD_DIR}/bitarray-${BITARRAY_VERSION}-cp${PYTHON_VERSION_SHORT}-cp${PYTHON_VERSION_SHORT}-win_amd64.whl
BITARRAY_WHEEL                  := ${BITARRAY_WHEEL-${WINEARCH}}
7ZIP_INSTALLER                  := ${DOWNLOAD_DIR}/7z938.msi

# native env & tools
CURL     := curl -s -f -L -m 600 --connect-timeout 30 --retry 10 --retry-max-time 5
WINE_DIR := /tmp/$(subst /,_,${CURDIR})/wine-${WINEARCH}
UNZIP    := unzip -q -o -DD

# installed files
PYTHON_INSTALLED   := ${WINE_DIR}/drive_c/Python${PYTHON_VERSION_SHORT}/python.exe
PIP_INSTALLED      := $(dir ${PYTHON_INSTALLED})Scripts/pip.exe
CXFREEZE_INSTALLED := $(dir ${PYTHON_INSTALLED})Scripts/cxfreeze
LXML_INSTALLED     := $(dir ${PYTHON_INSTALLED})Lib/site-packages/lxml/__init__.py
BITARRAY_INSTALLED := $(dir ${PYTHON_INSTALLED})Lib/site-packages/bitarray/__init__.py
7ZIP_INSTALLED     := ${WINE_DIR}/drive_c/7-Zip/7z.sfx

# wine env
WINE        := WINEPREFIX=${WINE_DIR} WINEARCH=${WINEARCH} WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all wine
WINE_PYTHON := ${WINE} ${PYTHON_INSTALLED}
WINE_PIP    := ${WINE} ${PIP_INSTALLED}

# temp dirs
TEST_LIB_DIR := ${WINE_DIR}/drive_c/music
OUTPUT_DIR   := sacad-${WINEARCH}


.PHONY: all test test_ut test_freeze fclean clean


all:: sacad_${WINEARCH}.7z sacad_${WINEARCH}.zip sacad_${WINEARCH}.exe

test:: test_ut test_freeze

print-%:
	@echo $*=$($*)


#
# End targets
#

sacad_${WINEARCH}.7z: ${OUTPUT_DIR}/sacad.exe ${OUTPUT_DIR}/sacad_r.exe ${OUTPUT_DIR}/LICENSE ${OUTPUT_DIR}/readme.txt
	7z a -t7z -mx9 $@ ${OUTPUT_DIR} > /dev/null

sacad_${WINEARCH}.zip: ${OUTPUT_DIR}/sacad.exe ${OUTPUT_DIR}/sacad_r.exe ${OUTPUT_DIR}/LICENSE ${OUTPUT_DIR}/readme.txt
	7z a -tzip -mx9 $@ ${OUTPUT_DIR} > /dev/null

sacad_${WINEARCH}.exe: ${7ZIP_INSTALLED} sacad_${WINEARCH}.7z
	cat $^ > $@


#
# Intermediate targets
#

${OUTPUT_DIR}/sacad.exe: ${CXFREEZE_INSTALLED} ${LXML_INSTALLED} ${BITARRAY_INSTALLED} .requirements
	mkdir -p $(dir $@)
	# fix for incorrect dll path detection
	mkdir -p $(dir ${PYTHON_INSTALLED})Library/bin
	cp $(dir ${PYTHON_INSTALLED})sqlite3.dll $(dir ${PYTHON_INSTALLED})Library/bin/
	cd .. && ${WINE_PYTHON} freeze.py build_exe -b win/${OUTPUT_DIR} 2> /dev/null > /dev/null
	touch $@

${OUTPUT_DIR}/sacad_r.exe: ${OUTPUT_DIR}/sacad.exe

${OUTPUT_DIR}/LICENSE:
	mkdir -p $(dir $@)
	cp ../LICENSE $@

${OUTPUT_DIR}/readme.txt:
	mkdir -p $(dir $@)
	echo 'Get source, help and latest version at: https://github.com/desbma/sacad' > $@


#
# Tests
#

test_ut: ${LXML_INSTALLED} ${BITARRAY_INSTALLED} .requirements
	cd .. && ${WINE_PYTHON} setup.py test

test_freeze:: ${TEST_LIB_DIR}/test.jpg ${TEST_LIB_DIR}/test.png

${TEST_LIB_DIR}/test.jpg: ${OUTPUT_DIR}/sacad.exe
	mkdir -p $(dir $@)
	${WINE} $< "neu" "neu 2" 1000 $@ && test -f $@

${TEST_LIB_DIR}/sample.ogg: ${DOWNLOAD_DIR}/sample.ogg
	mkdir -p $(dir $@)
	cp $< $@

${TEST_LIB_DIR}/test.png: ${TEST_LIB_DIR}/sample.ogg ${OUTPUT_DIR}/sacad_r.exe
	${WINE} ${OUTPUT_DIR}/sacad_r.exe $(dir $@) 300 $(notdir $@) && test -f $@


#
# Installations
#

.requirements: ${PIP_INSTALLED} ${LXML_INSTALLED} ${BITARRAY_INSTALLED}
	cp -r $(dir ${PYTHON_INSTALLED})Lib/site-packages/* $(dir ${PYTHON_INSTALLED})
	cd .. && ${WINE_PIP} -qq install -r requirements.txt
	cd .. && ${WINE_PIP} -qq install .
	cp -r $(dir ${PYTHON_INSTALLED})Lib/site-packages/* $(dir ${PYTHON_INSTALLED})
	touch $@

${PYTHON_INSTALLED}: ${PYTHON_EMBEDDABLE_ARCHIVE}
	mkdir -p $(dir $@)
	${UNZIP} -d $(dir $@) $<
	${UNZIP} -d $(dir $@) $(dir $@)python${PYTHON_VERSION_SHORT}.zip
	rm $(dir $@)python${PYTHON_VERSION_SHORT}.zip

${PIP_INSTALLED}: ${PYTHON_INSTALLED} ${GET_PIP}
	${WINE_PYTHON} ${GET_PIP} install -qq
	cp -r $(dir ${PYTHON_INSTALLED})Lib/site-packages/* $(dir ${PYTHON_INSTALLED})
	touch $@

${CXFREEZE_INSTALLED}: ${CXFREEZE_WHEEL} ${PIP_INSTALLED}
	${WINE_PIP} -qq install $<
	touch $@

${LXML_INSTALLED}: ${LXML_WHEEL} ${PIP_INSTALLED}
	${WINE_PIP} -qq install $<
	touch $@

${BITARRAY_INSTALLED}: ${BITARRAY_WHEEL} ${PIP_INSTALLED}
	${WINE_PIP} -qq install $<
	touch $@

${7ZIP_INSTALLED}: ${7ZIP_INSTALLER}
	${WINE} msiexec /i $< /qb INSTALLDIR='c:\7-Zip'
	touch $@


#
# Downloads
#

${PYTHON_EMBEDDABLE_ARCHIVE}:
	mkdir -p $(dir $@)
	${CURL} https://www.python.org/ftp/python/${PYTHON_VERSION}/$(notdir $@) > $@

${GET_PIP}:
	mkdir -p $(dir $@)
	${CURL} https://bootstrap.pypa.io/$(notdir $@) > $@

${CXFREEZE_WHEEL-win32}:
	mkdir -p $(dir $@)
	${CURL} https://files.pythonhosted.org/packages/9c/73/200ff06563430919f6f52e161c9be5ce23cc23e22675896f8691f38a1542/$(notdir $@) > $@

${CXFREEZE_WHEEL-win64}:
	mkdir -p $(dir $@)
	${CURL} https://files.pythonhosted.org/packages/ab/29/fe15bfebe9c8d7d2fa82917dc55e8f24eac3ba05e8381c110445362e8171/$(notdir $@) > $@

${LXML_WHEEL-win32}:
	mkdir -p $(dir $@)
	${CURL} https://www.dropbox.com/s/v1ngl3vhyrfp41x/$(notdir $@) > $@

${LXML_WHEEL-win64}:
	mkdir -p $(dir $@)
	${CURL} https://www.dropbox.com/s/9bcvukf1yu3e8f0/$(notdir $@) > $@

${BITARRAY_WHEEL-win32}:
	mkdir -p $(dir $@)
	${CURL} https://www.dropbox.com/s/l0gfugydh9uv674/$(notdir $@) > $@

${BITARRAY_WHEEL-win64}:
	mkdir -p $(dir $@)
	${CURL} https://www.dropbox.com/s/1iw9sl2h3vdk87j/$(notdir $@) > $@

${7ZIP_INSTALLER}:
	mkdir -p $(dir $@)
	${CURL} http://www.7-zip.org/a/$(notdir $@) > $@.unckecked
	echo "673377a03f91ff0f7f384794934b767c3389e50d7dc308f7c73f4633121518b3e4af8d33cf282398a710577e12fbb963152591c3e29b1092c79530bb2d8aa882  $@.unckecked" | sha512sum --status -c - && mv $@.unckecked $@

${DOWNLOAD_DIR}/sample.ogg:
	mkdir -p $(dir $@)
	${CURL} https://www.dropbox.com/s/zg80jd35ie3aury/Hydrate-Kenny_Beltrey.ogg > $@


#
# Clean
#

fclean:
	-rm -Rf ${WINE_DIR}
	-rm -Rf ${OUTPUT_DIR} .requirements
	-rm -f sacad_${WINEARCH}.7z sacad_${WINEARCH}.zip sacad_${WINEARCH}.exe

clean: fclean
	-rm -Rf ${DOWNLOAD_DIR}
