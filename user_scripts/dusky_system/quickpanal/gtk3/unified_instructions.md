🎯 Dynamic GTK3/GTK4 Wayland Focus-Grab Integration Guide
[!NOTE]
Wayland's strict security model sandboxes applications and prevents windows from observing input events, such as mouse clicks, that occur outside their boundaries. This document outlines a unified native C extension (libwaylandgrab.so) and corresponding Python integration that requests the Wayland compositor (Hyprland) to handle "outside clicks" and dismiss popups or panels automatically.
🧠 1. Architectural Concept: Dynamic Runtime Symbol Resolution & Concurrency
In traditional setups, separate libraries are built for GTK3 and GTK4 because they use different APIs to extract the underlying Wayland surface pointer:
* GTK3: gtk_widget_get_window -> gdk_window_get_display -> gdk_wayland_window_get_wl_surface
* GTK4: gtk_native_get_surface -> gdk_surface_get_display -> gdk_wayland_surface_get_wl_surface
Linking directly to GTK at compile time creates rigid dependencies and separate binaries. To avoid this, our unified C extension utilizes Dynamic Loading (dlfcn.h) alongside a robust polling and threading architecture.
How it Works:
1. Strict Probing (RTLD_NOLOAD): Instead of hard-linking GTK headers, the extension uses dlopen(..., RTLD_LAZY | RTLD_NOLOAD). RTLD_NOLOAD is critical—it ensures we only interact with the GTK version (3 or 4) already running in the Python process, averting catastrophic toolkit co-loading crashes.
2. Backend Validation: Uses GObject's g_type_check_instance_is_a dynamically to strictly verify the extracted GDK display is genuinely running under a Wayland backend.
3. Thread-Safe Dispatching: Wayland events are monitored via a background C thread using poll() and an eventfd for non-blocking shutdown signaling. Wayland buffer backpressure (EAGAIN) is safely handled via POLLOUT.
4. GIL-Safe Callbacks: When a click-away event occurs, the C library dynamically resolves GLib's g_idle_add to hand execution back to the GTK main thread before firing the Python callback. This guarantees Python Global Interpreter Lock (GIL) safety without requiring complex thread handoffs in the Python layer.
📦 2. Source Code Reference (dusky.c)
This is the unified C extension source code. Place this file in ~/user_scripts/dusky_system/click_away_to_dismiss/dusky.c.
/*
* dusky.c — Unified Wayland Focus-Grab Extension (GTK3 + GTK4)
*
* This library dynamically detects the active GTK runtime using safe
* RTLD_NOLOAD probing to prevent catastrophic toolkit co-loading.
* It resolves thread-safety violations with Wayland proxies, implements 
* strict backend validation, and safely manages socket backpressure.
*/

#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <unistd.h>
#include <errno.h>
#include <stdint.h>
#include <sys/eventfd.h>
#include <wayland-client.h>
#include "hyprland-focus-grab-v1-client-protocol.h"

/* ── Global State & Synchronization ─────────────────────────────────── */

static struct hyprland_focus_grab_manager_v1 *grab_manager   = NULL;
static struct hyprland_focus_grab_v1         *active_grab    = NULL;
static struct wl_event_queue                 *custom_queue   = NULL;
static struct wl_display                     *global_display = NULL;

typedef void (*ClearedCallback)(void);
static ClearedCallback py_callback = NULL;

static pthread_mutex_t state_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_t dispatch_thread;
static bool thread_running = false;
static int shutdown_efd = -1;

/* ── Dynamic GLib/GTK Function Pointers ─────────────────────────────── */

typedef int (*fn_g_idle_add)(void *function, void *data);
static fn_g_idle_add g_idle_add_ptr = NULL;

typedef void* (*fn_gtk_get_ptr)(void*);
typedef struct wl_display* (*fn_gdk_get_wl_display)(void*);
typedef struct wl_surface* (*fn_gdk_get_wl_surface)(void*);

/* ── Registry Listener ──────────────────────────────────────────────── */

static void registry_handler(void *data, struct wl_registry *registry,
                            uint32_t id, const char *interface,
                            uint32_t version) {
   if (strcmp(interface, "hyprland_focus_grab_manager_v1") == 0) {
       grab_manager = wl_registry_bind(
           registry, id, &hyprland_focus_grab_manager_v1_interface, 1);
   }
}

static void registry_remover(void *data, struct wl_registry *registry,
                             uint32_t id) {}

static const struct wl_registry_listener registry_listener = {
   &registry_handler, &registry_remover
};

/* ── Thread-Safe Callback Wrapper (GIL Safety) ──────────────────────── */

static int idle_callback_wrapper(void *data) {
   ClearedCallback cb = NULL;

   pthread_mutex_lock(&state_mutex);
   cb = py_callback;
   pthread_mutex_unlock(&state_mutex);

   if (cb) {
       cb();
   }
   
   return 0; /* G_SOURCE_REMOVE */
}

static void grab_cleared(void *data, struct hyprland_focus_grab_v1 *grab) {
   pthread_mutex_lock(&state_mutex);
   if (active_grab == grab && g_idle_add_ptr) {
       g_idle_add_ptr((void*)idle_callback_wrapper, NULL);
   }
   pthread_mutex_unlock(&state_mutex);
}

static const struct hyprland_focus_grab_v1_listener grab_listener = {
   .cleared = grab_cleared
};

/* ── Background Dispatch Thread ─────────────────────────────────────── */

static void *dispatch_thread_func(void *arg) {
   int wl_fd = wl_display_get_fd(global_display);
   struct pollfd pfds[2];
   
   pfds[0].fd = wl_fd;
   pfds[0].events = POLLIN;
   pfds[1].fd = shutdown_efd;
   pfds[1].events = POLLIN;

   while (1) {
       while (wl_display_prepare_read_queue(global_display, custom_queue) != 0) {
           wl_display_dispatch_queue_pending(global_display, custom_queue);
       }
       
       pthread_mutex_lock(&state_mutex);
       int flush_ret = wl_display_flush(global_display);
       if (flush_ret < 0 && errno == EAGAIN) {
           pfds[0].events |= POLLOUT; /* Handle Wayland buffer backpressure */
       } else {
           pfds[0].events &= ~POLLOUT;
       }
       pthread_mutex_unlock(&state_mutex);

       int ret = poll(pfds, 2, -1);
       if (ret < 0) {
           wl_display_cancel_read(global_display);
           if (errno == EINTR) continue;
           break;
       }

       /* Enforce clean shutdown event priority */
       if (pfds[1].revents & POLLIN) {
           wl_display_cancel_read(global_display);
           break; 
       }

       /* Strict fd event validation for Wayland socket */
       if (pfds[0].revents & (POLLERR | POLLHUP | POLLNVAL)) {
           wl_display_cancel_read(global_display);
           break; 
       }

       if (pfds[0].revents & POLLIN) {
           if (wl_display_read_events(global_display) < 0) {
               break;
           }
       } else {
           wl_display_cancel_read(global_display);
       }

       wl_display_dispatch_queue_pending(global_display, custom_queue);
   }
   return NULL;
}

/* ── Toolkit Resolution & Extraction ────────────────────────────────── */

static bool is_wayland_display(void *gdk_display, void *gdk_handle) {
   if (!gdk_display || !gdk_handle) return false;
   
   /* Removed RTLD_NOLOAD: GObject is safe to load if isolated in Python memory */
   void *gobj_handle = dlopen("libgobject-2.0.so.0", RTLD_LAZY);
   if (!gobj_handle) return false;

   typedef unsigned long GType;
   typedef int (*fn_check_is_a)(void*, GType);
   typedef GType (*fn_get_type)(void);

   fn_check_is_a check_is_a = (fn_check_is_a)dlsym(gobj_handle, "g_type_check_instance_is_a");
   fn_get_type get_wl_display_type = (fn_get_type)dlsym(gdk_handle, "gdk_wayland_display_get_type");
       
   if (!check_is_a || !get_wl_display_type) return false;
   
   return check_is_a(gdk_display, get_wl_display_type());
}

static bool resolve_wayland_surfaces(void *gtk_ptr,
                                    struct wl_display **out_display,
                                    struct wl_surface **out_surface) {
   void *toolkit_handle = NULL;
   bool is_gtk4 = false;

   /* RTLD_NOLOAD is MANDATORY here to prevent fatal GTK co-loading crashes */
   if ((toolkit_handle = dlopen("libgtk-4.so.1", RTLD_LAZY | RTLD_NOLOAD))) {
       is_gtk4 = true;
   } else if ((toolkit_handle = dlopen("libgtk-3.so.0", RTLD_LAZY | RTLD_NOLOAD))) {
       is_gtk4 = false;
   } else {
       fprintf(stderr, "[libwaylandgrab] Error: Neither GTK3 nor GTK4 is resident.\n");
       return false;
   }

   if (is_gtk4) {
       fn_gtk_get_ptr get_surface = (fn_gtk_get_ptr)dlsym(toolkit_handle, "gtk_native_get_surface");
       fn_gtk_get_ptr get_display = (fn_gtk_get_ptr)dlsym(toolkit_handle, "gdk_surface_get_display");
       fn_gdk_get_wl_display get_wl_display = (fn_gdk_get_wl_display)dlsym(toolkit_handle, "gdk_wayland_display_get_wl_display");
       fn_gdk_get_wl_surface get_wl_surface = (fn_gdk_get_wl_surface)dlsym(toolkit_handle, "gdk_wayland_surface_get_wl_surface");

       if (get_surface && get_display && get_wl_display && get_wl_surface) {
           void *gdk_surface = get_surface(gtk_ptr);
           if (gdk_surface) {
               void *gdk_display = get_display(gdk_surface);
               if (is_wayland_display(gdk_display, toolkit_handle)) {
                   *out_display = get_wl_display(gdk_display);
                   *out_surface = get_wl_surface(gdk_surface);
                   if (*out_display && *out_surface) return true;
               }
           }
       }
   } else {
       /* RTLD_NOLOAD is MANDATORY here to prevent loading GDK3 into a GTK4 app */
       void *gdk3_handle = dlopen("libgdk-3.so.0", RTLD_LAZY | RTLD_NOLOAD);
       if (!gdk3_handle) return false;

       fn_gtk_get_ptr get_window = (fn_gtk_get_ptr)dlsym(toolkit_handle, "gtk_widget_get_window");
       fn_gtk_get_ptr get_display = (fn_gtk_get_ptr)dlsym(gdk3_handle, "gdk_window_get_display");
       fn_gdk_get_wl_display get_wl_display = (fn_gdk_get_wl_display)dlsym(gdk3_handle, "gdk_wayland_display_get_wl_display");
       fn_gdk_get_wl_surface get_wl_surface = (fn_gdk_get_wl_surface)dlsym(gdk3_handle, "gdk_wayland_window_get_wl_surface");

       if (get_window && get_display && get_wl_display && get_wl_surface) {
           void *gdk_window = get_window(gtk_ptr);
           if (gdk_window) {
               void *gdk_display = get_display(gdk_window);
               if (is_wayland_display(gdk_display, gdk3_handle)) {
                   *out_display = get_wl_display(gdk_display);
                   *out_surface = get_wl_surface(gdk_window);
                   if (*out_display && *out_surface) return true;
               }
           }
       }
   }

   fprintf(stderr, "[libwaylandgrab] Error: Toolkit is not running under the Wayland backend.\n");
   return false;
}

/* ── Public API ─────────────────────────────────────────────────────── */

void init_wayland_grab(void *gtk_window_ptr, ClearedCallback cb) {
   if (!gtk_window_ptr) return;

   pthread_mutex_lock(&state_mutex);

   if (thread_running) {
       fprintf(stderr, "[libwaylandgrab] Warning: Grab already initialized. Call destroy first.\n");
       pthread_mutex_unlock(&state_mutex);
       return;
   }

   py_callback = cb;
   struct wl_surface *wl_surface = NULL;

   if (!resolve_wayland_surfaces(gtk_window_ptr, &global_display, &wl_surface)) {
       pthread_mutex_unlock(&state_mutex);
       return;
   }

   if (!g_idle_add_ptr) {
       /* Removed RTLD_NOLOAD: GLib is safe to load and required for the callback */
       void *glib_handle = dlopen("libglib-2.0.so.0", RTLD_LAZY);
       if (glib_handle) {
           g_idle_add_ptr = (fn_g_idle_add)dlsym(glib_handle, "g_idle_add");
       }

       /* Prevent silent callback failure by loudly aborting if GLib fails to load */
       if (!g_idle_add_ptr) {
           fprintf(stderr, "[libwaylandgrab] Fatal: Failed to resolve g_idle_add. Callbacks will silently fail. Aborting.\n");
           pthread_mutex_unlock(&state_mutex);
           return;
       }
   }

   shutdown_efd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
   if (shutdown_efd < 0) {
       pthread_mutex_unlock(&state_mutex);
       return;
   }

   custom_queue = wl_display_create_queue(global_display);
   struct wl_registry *registry = wl_display_get_registry(global_display);

   wl_proxy_set_queue((struct wl_proxy *)registry, custom_queue);
   wl_registry_add_listener(registry, &registry_listener, NULL);
   wl_display_roundtrip_queue(global_display, custom_queue);
   wl_registry_destroy(registry);

   if (!grab_manager) {
       fprintf(stderr, "[libwaylandgrab] Error: hyprland_focus_grab_manager_v1 is unsupported by compositor.\n");
       wl_event_queue_destroy(custom_queue);
       custom_queue = NULL;
       close(shutdown_efd);
       shutdown_efd = -1;
       pthread_mutex_unlock(&state_mutex);
       return;
   }

   active_grab = hyprland_focus_grab_manager_v1_create_grab(grab_manager);
   wl_proxy_set_queue((struct wl_proxy *)active_grab, custom_queue);
   
   hyprland_focus_grab_v1_add_listener(active_grab, &grab_listener, NULL);
   hyprland_focus_grab_v1_add_surface(active_grab, wl_surface);
   hyprland_focus_grab_v1_commit(active_grab);
   
   wl_display_flush(global_display);

   if (pthread_create(&dispatch_thread, NULL, dispatch_thread_func, NULL) == 0) {
       thread_running = true;
   } else {
       hyprland_focus_grab_v1_destroy(active_grab);
       active_grab = NULL;
       wl_event_queue_destroy(custom_queue);
       custom_queue = NULL;
       close(shutdown_efd);
       shutdown_efd = -1;
   }

   pthread_mutex_unlock(&state_mutex);
}

void destroy_wayland_grab() {
   pthread_mutex_lock(&state_mutex);
   bool do_join = thread_running;
   int efd = shutdown_efd;
   pthread_mutex_unlock(&state_mutex);

   /* Signal eventfd and wait for the polling thread to safely exit bounds */
   if (do_join && efd >= 0) {
       uint64_t val = 1;
       if (write(efd, &val, sizeof(val)) == -1) {
           /* Fallback, benign write failure */
       }
       pthread_join(dispatch_thread, NULL);
   }

   /* Strict proxy destruction order after dispatch thread is confirmed dead */
   pthread_mutex_lock(&state_mutex);
   
   if (active_grab) {
       hyprland_focus_grab_v1_destroy(active_grab);
       active_grab = NULL;
   }
   
   if (grab_manager) {
       hyprland_focus_grab_manager_v1_destroy(grab_manager);
       grab_manager = NULL;
   }

   if (custom_queue) {
       wl_event_queue_destroy(custom_queue);
       custom_queue = NULL;
   }

   if (shutdown_efd >= 0) {
       close(shutdown_efd);
       shutdown_efd = -1;
   }
   
   thread_running = false;
   py_callback = NULL;
   global_display = NULL; 
   
   pthread_mutex_unlock(&state_mutex);
}

🛠️ 3. Compilation and Code-Generation Commands
To compile this unified extension, first translate the XML definition into C protocol code, and then compile it without any GTK compiler options.
TARGET="$HOME/user_scripts/dusky_system/click_away_to_dismiss"

# 1. Generate client header protocol
wayland-scanner client-header \
 "$TARGET/hyprland-focus-grab-v1.xml" \
 "$TARGET/hyprland-focus-grab-v1-client-protocol.h"

# 2. Generate client glue code
wayland-scanner private-code \
 "$TARGET/hyprland-focus-grab-v1.xml" \
 "$TARGET/hyprland-focus-grab-v1-client-protocol.c"

# 3. Compile the shared library (Zero GTK flags, requires dynamic loading libraries)
gcc -shared -fPIC -o "$TARGET/libwaylandgrab.so" \
 "$TARGET/dusky.c" \
 "$TARGET/hyprland-focus-grab-v1-client-protocol.c" \
 -lwayland-client -lpthread -ldl

🐍 4. Unified Python Gtk3/Gtk4 Integration Boilerplate
This boilerplate logic gracefully detects and works for both GTK3 and GTK4, accounting for memory bounds and API changes.
Step 4.1: Library Loading (Walkie-Talkie Setup)
Near the top of your python script, load the library and map the callback types.
import ctypes
import os
import logging
from gi.repository import GLib, Gtk

# Define path to the shared library
_grab_lib_path = os.path.expanduser("~/user_scripts/dusky_system/click_away_to_dismiss/libwaylandgrab.so")

try:
   LIBGRAB = ctypes.CDLL(_grab_lib_path)
   # Callback type matches: void callback_name(void)
   CB_TYPE = ctypes.CFUNCTYPE(None)
except OSError:
   logging.warning(f"Failed to load Wayland Grab Library at {_grab_lib_path}. Outside click dismissal is disabled.")
   LIBGRAB = None

Step 4.2: Component Integration
Implement this code in your window implementation class.
[!WARNING]
It is critical to keep a persistent reference to the callback wrapper in python memory (e.g., self._grab_cb). If not retained, Python's Garbage Collector will reclaim the callback object, resulting in a segmentation fault.
class QuickPanelWindow(Gtk.Window):
   def __init__(self, **kwargs):
       super().__init__(**kwargs)

       # Detect GTK version to route events appropriately
       self.is_gtk4 = Gtk.get_major_version() == 4

       # 1. Prevent garbage collection of our Python callback wrapper
       if LIBGRAB:
           self._grab_cb = CB_TYPE(self._on_grab_cleared)
       else:
           self._grab_cb = None

       # 2. Connect window events
       # "map" fires when the window is mapped to a monitor surface
       self.connect("map", self._on_map)
       
       # Connect to visibility/destruction handlers to cleanly release focus grab
       self.connect("hide", self._on_hide)
       
       if self.is_gtk4:
           self.connect("close-request", self._on_close_request)
       else:
           self.connect("delete-event", self._on_delete_event)

   def _on_map(self, *args):
       """Triggers the moment GTK attaches pixels to the window on screen."""
       self._activate_grab()

   def _activate_grab(self):
       """Registers the window to intercept focus and register click-away."""
       if LIBGRAB and self.get_visible() and self._grab_cb:
           ptr_val = hash(self)
           
           # Guarantee a positive unsigned 64-bit bounds memory address pointer for c_void_p
           # Prevents C library validation failure if PyGObject passes a negative address representation
           if ptr_val < 0:
               ptr_val += 1 << (ctypes.sizeof(ctypes.c_void_p) * 8)
               
           window_ptr = ctypes.c_void_p(ptr_val)
           LIBGRAB.init_wayland_grab(window_ptr, self._grab_cb)

   def _on_grab_cleared(self):
       """
       Callback invoked when a click-away is detected. 
       Because the C extension internally uses g_idle_add, this is automatically
       executed safely on the GTK main thread (GIL is safe). We optionally wrap it 
       in GLib.idle_add to cleanly queue the UI state change for the next loop.
       """
       if self.is_gtk4:
           GLib.idle_add(self.set_visible, False)
       else:
           GLib.idle_add(self.hide)

   def _on_hide(self, *args):
       """Ensures focus grab is cleanly destroyed when hidden."""
       if LIBGRAB:
           LIBGRAB.destroy_wayland_grab()

   # --- GTK4 Close Handler ---
   def _on_close_request(self, _window) -> bool:
       self.set_visible(False)
       return True

   # --- GTK3 Close Handler ---
   def _on_delete_event(self, _window, _event) -> bool:
       """Hides rather than destroying window on close."""
       self.hide()
       return True

🔍 5. Architectural Considerations
Feature
	GTK3 Support
	GTK4 Support
	Address Reference
	hash(self) with bitwise unsigned correction.
	hash(self) with bitwise unsigned correction.
	Window State Signal
	Uses map to trigger grab when drawn.
	Uses map to trigger grab when drawn.
	Window Close Signal
	delete-event intercepts window destruction.
	close-request intercepts window destruction.
	Interface Resolution
	dlopen libgtk-3.so.0 + RTLD_NOLOAD
	dlopen libgtk-4.so.1 + RTLD_NOLOAD
	Thread Invocation
	Callback dynamically dispatched via GLib g_idle_add inside C.
	Callback dynamically dispatched via GLib g_idle_add inside C.
	By separating compilation from framework headers, utilizing RTLD_NOLOAD for strict runtime resolution, and managing GIL constraints internally via g_idle_add, you guarantee a single robust binary deployment immune to framework co-loading crashes.
