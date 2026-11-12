TARGET := iphone:clang:latest:15.0
ARCHS = arm64 arm64e
INSTALL_TARGET_PROCESSES = No\ Man\'s\ Sky

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = NMSMenu

NMSMenu_FILES = Tweak.m NMSPrefs.m NMSCheatEngine.m NMSSaveTool.m NMSMenuWindow.m
NMSMenu_CFLAGS = -fobjc-arc -Wno-deprecated-declarations
NMSMenu_FRAMEWORKS = UIKit Foundation CoreGraphics QuartzCore
NMSMenu_LIBRARIES = z
NMSMenu_PRIVATE_FRAMEWORKS =

include $(THEOS_MAKE_PATH)/tweak.mk

after-install::
	install.exec "killall -9 'No Man's Sky' || true"
