/*
 * Minimal C++ ABI Runtime for Subleq Linux
 * 
 * Provides the essential __cxa_* functions needed for C++ exception handling
 * with LLVM's SJLJ (SetJmp/LongJmp) exception model.
 * 
 * This is a minimal implementation - not thread-safe, single exception only.
 */

#include <stdlib.h>
#include <string.h>
#include <setjmp.h>

/* Debug output - DISABLED */
static void debug_char(char c) { (void)c; }

/* Forward declarations for unwind API */
struct _Unwind_Exception;
extern int _Unwind_SjLj_RaiseException(struct _Unwind_Exception *);

/*
 * _Unwind_Exception structure - must match sjlj_unwind.c
 */
struct _Unwind_Exception {
    unsigned long long exception_class;
    void (*exception_cleanup)(int, struct _Unwind_Exception *);
    unsigned long private_1;
    unsigned long private_2;
};

/*
 * Full C++ exception header - placed before the thrown object in memory.
 * This layout MUST match sjlj_unwind.c's __cxa_exception struct.
 * 
 * Memory layout:
 *   [__cxa_exception header][thrown object data]
 *                           ^-- pointer returned by allocate_exception
 */
struct __cxa_exception {
    /* C++ ABI fields */
    void *exceptionType;                    /* offset 0 */
    void (*exceptionDestructor)(void *);    /* offset 4 */
    void (*unexpectedHandler)(void);        /* offset 8 */
    void (*terminateHandler)(void);         /* offset 12 */
    struct __cxa_exception *nextException;  /* offset 16 */
    int handlerCount;                       /* offset 20 */
    int handlerSwitchValue;                 /* offset 24 */
    const void *actionRecord;               /* offset 28 */
    const void *languageSpecificData;       /* offset 32 */
    void *catchTemp;                        /* offset 36 */
    void *adjustedPtr;                      /* offset 40 */
    /* Embedded _Unwind_Exception header */
    struct _Unwind_Exception unwindHeader;  /* offset 44 */
};

/*
 * Per-thread exception state (simplified - assumes single threaded)
 */
static struct {
    struct __cxa_exception *caughtExceptions;
    unsigned int uncaughtExceptions;
    void *currentException;  /* Pointer to thrown object (after header) */
} __cxa_eh_globals;

/*
 * SJLJ exception buffer - set by SjLjEHPrepare-generated code
 */
jmp_buf *__sjlj_exception_buf = NULL;

/*
 * Allocate memory for an exception object
 */
void *__cxa_allocate_exception(size_t thrown_size) {
    size_t size = sizeof(struct __cxa_exception) + thrown_size;
    struct __cxa_exception *ex = (struct __cxa_exception *)malloc(size);
    if (!ex) {
        /* Out of memory during exception - abort */
        abort();
    }
    memset(ex, 0, sizeof(struct __cxa_exception));
    return (void *)(ex + 1);  /* Return pointer to thrown object area */
}

/*
 * Free an exception object
 */
void __cxa_free_exception(void *thrown_object) {
    if (!thrown_object) return;
    struct __cxa_exception *ex = 
        ((struct __cxa_exception *)thrown_object) - 1;
    free(ex);
}

/*
 * Initialize a primary exception header without throwing.
 * Used by libc++ for std::make_exception_ptr to avoid throw+catch overhead.
 * Returns the __cxa_exception header pointer.
 */
void __cxa_decrement_exception_refcount(void *p);  /* forward declaration */

static void exception_cleanup_func(int reason, struct _Unwind_Exception *unwind_exception) {
    (void)reason;
    struct __cxa_exception *ex = (struct __cxa_exception *)((char *)unwind_exception - 
        __builtin_offsetof(struct __cxa_exception, unwindHeader));
    __cxa_decrement_exception_refcount((void *)(ex + 1));
}

struct __cxa_exception *__cxa_init_primary_exception(
        void *object, void *tinfo, void (*dest)(void *)) {
    struct __cxa_exception *ex = 
        ((struct __cxa_exception *)object) - 1;
    ex->exceptionType = tinfo;
    ex->exceptionDestructor = dest;
    ex->unexpectedHandler = 0;
    ex->terminateHandler = 0;
    /* Set up exception class - "CLNGC++\0" */
    ex->unwindHeader.exception_class = 0x434C4E47432B2B00ULL;
    ex->unwindHeader.exception_cleanup = exception_cleanup_func;
    return ex;
}

/*
 * Throw an exception
 * 
 * This calls the SJLJ unwinder to find and jump to the appropriate handler.
 */
void __cxa_throw(void *thrown_object, void *tinfo, 
                 void (*destructor)(void *)) __attribute__((noreturn));
void __cxa_throw(void *thrown_object, void *tinfo, 
                 void (*destructor)(void *)) {
    debug_char('T'); debug_char('H'); debug_char('R'); debug_char('\n');  /* THR = throw */
    
    struct __cxa_exception *ex = 
        ((struct __cxa_exception *)thrown_object) - 1;
    
    ex->exceptionType = tinfo;
    ex->exceptionDestructor = destructor;
    __cxa_eh_globals.uncaughtExceptions++;
    __cxa_eh_globals.currentException = thrown_object;

    /* Set up the exception class - "CLNGC++\0" */
    ex->unwindHeader.exception_class = 0x434C4E47432B2B00ULL;
    ex->unwindHeader.exception_cleanup = 0;
    
    debug_char('U'); debug_char('W'); debug_char('\n');  /* UW = call unwinder */
    /* Call the unwinder - pass pointer to embedded unwindHeader */
    _Unwind_SjLj_RaiseException(&ex->unwindHeader);
    
    debug_char('N'); debug_char('H'); debug_char('!'); debug_char('\n');  /* NH! = no handler */
    /* If we get here, no handler was found - terminate */
    abort();
}

/*
 * Begin a catch block
 * 
 * The personality function passes &__cxa_exception::unwindHeader (a _Unwind_Exception*).
 * We need to convert this back to the thrown object pointer.
 */
void *__cxa_begin_catch(void *exception_object) {
    struct __cxa_exception *ex;
    void *thrown_object;
    
    if (!exception_object) {
        /* Use stored thrown object if none passed */
        thrown_object = __cxa_eh_globals.currentException;
        if (!thrown_object) return 0;
        ex = ((struct __cxa_exception *)thrown_object) - 1;
    } else {
        /* exception_object is actually a _Unwind_Exception* pointing to unwindHeader */
        /* Convert back to __cxa_exception* using offsetof */
        struct _Unwind_Exception *unwind_ex = (struct _Unwind_Exception *)exception_object;
        ex = (struct __cxa_exception *)((char *)unwind_ex - 
            __builtin_offsetof(struct __cxa_exception, unwindHeader));
        thrown_object = (void *)(ex + 1);  /* Thrown object follows header */
    }
    
    ex->handlerCount++;
    ex->nextException = __cxa_eh_globals.caughtExceptions;
    __cxa_eh_globals.caughtExceptions = ex;
    
    if (__cxa_eh_globals.uncaughtExceptions > 0) {
        __cxa_eh_globals.uncaughtExceptions--;
    }
    
    return thrown_object;
}

/*
 * End a catch block
 * 
 * Called at the end of a catch clause to clean up the exception.
 */
void __cxa_end_catch(void) {
    struct __cxa_exception *ex = __cxa_eh_globals.caughtExceptions;
    if (!ex)
        return;
    
    ex->handlerCount--;
    if (ex->handlerCount == 0) {
        __cxa_eh_globals.caughtExceptions = ex->nextException;
        
        /* Call destructor if present */
        if (ex->exceptionDestructor) {
            ex->exceptionDestructor((void *)(ex + 1));
        }
        
        /* Free the exception */
        __cxa_free_exception((void *)(ex + 1));
    }
}

/*
 * Rethrow the current exception
 * 
 * Called by 'throw;' - resumes exception propagation with the current exception.
 */
extern void _Unwind_SjLj_Resume(struct _Unwind_Exception *) __attribute__((noreturn));

void __cxa_rethrow(void) __attribute__((noreturn));
void __cxa_rethrow(void) {
    struct __cxa_exception *ex = __cxa_eh_globals.caughtExceptions;
    if (!ex) {
        /* No current exception to rethrow */
        abort();
    }
    
    /* Mark as uncaught again */
    __cxa_eh_globals.uncaughtExceptions++;
    
    /* Decrement handler count since we're leaving the catch */
    ex->handlerCount--;
    
    /* Remove from caught list but don't free - it's being rethrown */
    __cxa_eh_globals.caughtExceptions = ex->nextException;
    
    /* Resume unwinding - pass the unwind header */
    _Unwind_SjLj_Resume(&ex->unwindHeader);
    
    /* Never reached */
    abort();
}

/*
 * Get current exception object
 */
void *__cxa_current_exception(void) {
    return __cxa_eh_globals.currentException;
}

/*
 * Get uncaught exception count (C++ ABI)
 */
int __cxa_uncaught_exceptions(void) {
    return (int)__cxa_eh_globals.uncaughtExceptions;
}

/*
 * Legacy: check if there is an uncaught exception
 */
int __cxa_uncaught_exception(void) {
    return __cxa_eh_globals.uncaughtExceptions > 0;
}

/*
 * Exception reference counting (minimal single-threaded stubs)
 * In a full implementation these would manage shared ownership of
 * exception_ptr objects. For our single-threaded runtime, no-ops suffice.
 */
void __cxa_increment_exception_refcount(void *p) {
    (void)p;
}

void __cxa_decrement_exception_refcount(void *p) {
    (void)p;
}

/*
 * Get current primary exception for exception_ptr
 * Returns a pointer that can be used with rethrow_primary_exception.
 */
void *__cxa_current_primary_exception(void) {
    struct __cxa_exception *ex = __cxa_eh_globals.caughtExceptions;
    if (!ex) return 0;
    /* Return pointer to thrown object */
    return (void *)(ex + 1);
}

/*
 * Rethrow a primary exception (for std::rethrow_exception)
 */
void __cxa_rethrow_primary_exception(void *p) __attribute__((noreturn));
void __cxa_rethrow_primary_exception(void *p) {
    if (!p) {
        abort();
    }
    /* Set as current and rethrow */
    __cxa_eh_globals.currentException = p;
    __cxa_eh_globals.uncaughtExceptions++;

    struct __cxa_exception *ex = ((struct __cxa_exception *)p) - 1;
    _Unwind_SjLj_RaiseException(&ex->unwindHeader);

    /* If we get here, no handler found */
    abort();
}

/* Personality function is now implemented in sjlj_unwind.c */

/*
 * Pure virtual function call handler
 * 
 * Called when a pure virtual function is invoked (programming error).
 */
void __cxa_pure_virtual(void) {
    /* Pure virtual called - programming error, just abort */
    abort();
}

/*
 * Deleted virtual function call handler
 */
void __cxa_deleted_virtual(void) {
    /* Deleted virtual called - programming error, just abort */
    abort();
}

/*
 * Called when an exception escapes a noexcept function or during cleanup
 * This is an LLVM/clang internal function.
 */
void __clang_call_terminate(void *exception) __attribute__((noreturn));
void __clang_call_terminate(void *exception) {
    (void)exception;
    /* Exception during cleanup - terminate */
    abort();
}

/*
 * Guard variable functions for thread-safe static initialization
 * (simplified - not thread-safe, single threaded assumed)
 */
int __cxa_guard_acquire(long long *guard) {
    char *g = (char *)guard;
    if (*g) return 0;  /* Already initialized */
    g[1] = 1;          /* Mark as in-progress */
    return 1;          /* Proceed with initialization */
}

void __cxa_guard_release(long long *guard) {
    char *g = (char *)guard;
    *g = 1;  /* Mark as initialized */
}

void __cxa_guard_abort(long long *guard) {
    char *g = (char *)guard;
    g[1] = 0;  /* Clear in-progress flag */
}

/* Note: __cxa_bad_cast and __cxa_bad_typeid are now in cxxabi_typeinfo.cpp
   where they can properly throw std::bad_cast and std::bad_typeid exceptions */

/*
 * C++ memory management operators
 * These are minimal stubs that redirect to malloc/free.
 */

/* operator new(size_t) - _Znwj on 32-bit */
void *_Znwj(unsigned int size) {
    return malloc(size);
}

/* operator new[](size_t) - _Znaj on 32-bit */
void *_Znaj(unsigned int size) {
    return malloc(size);
}

/* operator delete(void*) - _ZdlPv */
void _ZdlPv(void *ptr) {
    free(ptr);
}

/* operator delete[](void*) - _ZdaPv */
void _ZdaPv(void *ptr) {
    free(ptr);
}

/* operator delete(void*, size_t) - _ZdlPvj (C++14 sized deallocation) */
void _ZdlPvj(void *ptr, unsigned int size) {
    (void)size;
    free(ptr);
}

/* operator delete[](void*, size_t) - _ZdaPvj */ 
void _ZdaPvj(void *ptr, unsigned int size) {
    (void)size;
    free(ptr);
}
