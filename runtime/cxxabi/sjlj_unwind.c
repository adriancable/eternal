/* Complete SJLJ Exception Handling Runtime for Subleq
 *
 * This implements setjmp/longjmp-based C++ exception handling.
 * Based on LLVM's libunwind/src/Unwind-sjlj.c and libcxxabi.
 *
 * SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
 */

#include <stdint.h>
#include <stddef.h>

/* SJLJ uses a 5-element void* buffer for __builtin_setjmp/__builtin_longjmp.
 * The layout is target-specific but typically:
 *   [0] = frame pointer
 *   [1] = dispatch address (where to jump on longjmp)
 *   [2] = stack pointer
 *   [3-4] = reserved
 */

/* Forward declaration for abort */
extern void abort(void) __attribute__((noreturn));

/* ========================================================================= */
/* Configuration and Constants                                               */
/* ========================================================================= */

/* Unwind reason codes */
typedef enum {
    _URC_NO_REASON = 0,
    _URC_FOREIGN_EXCEPTION_CAUGHT = 1,
    _URC_FATAL_PHASE2_ERROR = 2,
    _URC_FATAL_PHASE1_ERROR = 3,
    _URC_NORMAL_STOP = 4,
    _URC_END_OF_STACK = 5,
    _URC_HANDLER_FOUND = 6,
    _URC_INSTALL_CONTEXT = 7,
    _URC_CONTINUE_UNWIND = 8
} _Unwind_Reason_Code;

/* Unwind action flags */
typedef int _Unwind_Action;
#define _UA_SEARCH_PHASE    1
#define _UA_CLEANUP_PHASE   2
#define _UA_HANDLER_FRAME   4
#define _UA_FORCE_UNWIND    8
#define _UA_END_OF_STACK   16

/* DWARF encoding constants */
#define DW_EH_PE_omit   0xFF
#define DW_EH_PE_absptr 0x00
#define DW_EH_PE_uleb128 0x01
#define DW_EH_PE_udata4 0x03
#define DW_EH_PE_sdata4 0x0B
#define DW_EH_PE_pcrel  0x10
#define DW_EH_PE_indirect 0x80

/* C++ ABI exception class - "CLNGC++\0" */
static const uint64_t kOurExceptionClass = 0x434C4E47432B2B00ULL;
static const uint64_t kOurDependentExceptionClass = 0x434C4E47432B2B01ULL;

/* Forward declarations */
struct _Unwind_Exception;
struct _Unwind_Context;

typedef _Unwind_Reason_Code (*_Unwind_Personality_Fn)(
    int version,
    _Unwind_Action actions,
    uint64_t exceptionClass,
    struct _Unwind_Exception *exceptionObject,
    struct _Unwind_Context *context);

typedef void (*_Unwind_Exception_Cleanup_Fn)(
    _Unwind_Reason_Code reason,
    struct _Unwind_Exception *exc);

/* ========================================================================= */
/* Data Structures                                                           */
/* ========================================================================= */

/* _Unwind_Exception - passed to personality function */
struct _Unwind_Exception {
    uint64_t exception_class;
    _Unwind_Exception_Cleanup_Fn exception_cleanup;
    uintptr_t private_1;    /* Used by unwinder: 0 = normal, else = forced stop fn */
    uintptr_t private_2;    /* Used by unwinder: handler frame context */
};

/* Function context for SJLJ - one per function with try/catch
 * Layout matches what SjLjEHPrepare creates:
 *   [0] __prev - pointer to previous context
 *   [1] call_site - current call site index (32-bit)
 *   [2-5] __data[4] - resume parameters (4 x 32-bit)
 *   [6] __personality - personality function pointer
 *   [7] __lsda - LSDA pointer
 *   [8-12] __jbuf[5] - jump buffer (5 x void*)
 */
struct _Unwind_FunctionContext {
    struct _Unwind_FunctionContext *prev;   /* Previous context in chain */
    uint32_t resumeLocation;                /* Call site index (1-based) */
    uint32_t resumeParameters[4];           /* [0]=exc ptr, [1]=selector */
    _Unwind_Personality_Fn personality;     /* Personality function */
    uintptr_t lsda;                         /* Language Specific Data Area */
    void *jbuf[5];                          /* SJLJ jump buffer */
};

typedef struct _Unwind_FunctionContext *_Unwind_FunctionContext_t;

/* __cxa_exception header - before the thrown object */
struct __cxa_exception {
    void *exceptionType;        /* Type of the exception */
    void (*exceptionDestructor)(void *);
    void (*unexpectedHandler)(void);
    void (*terminateHandler)(void);
    struct __cxa_exception *nextException;
    int handlerCount;
    int handlerSwitchValue;
    const uint8_t *actionRecord;
    const uint8_t *languageSpecificData;
    void *catchTemp;
    void *adjustedPtr;
    struct _Unwind_Exception unwindHeader;
};

/* ========================================================================= */
/* Global State                                                              */
/* ========================================================================= */

/* Global chain of function contexts (single-threaded) */
static struct _Unwind_FunctionContext *SjLjContextStack = NULL;

/* ========================================================================= */
/* Helper Functions                                                          */
/* ========================================================================= */

/* Read unsigned LEB128 value */
static uintptr_t readULEB128(const uint8_t **data) {
    uintptr_t result = 0;
    uintptr_t shift = 0;
    uint8_t byte;
    const uint8_t *p = *data;
    do {
        byte = *p++;
        result |= ((uintptr_t)(byte & 0x7F)) << shift;
        shift += 7;
    } while (byte & 0x80);
    *data = p;
    return result;
}

/* Read signed LEB128 value */
static intptr_t readSLEB128(const uint8_t **data) {
    uintptr_t result = 0;
    uintptr_t shift = 0;
    uint8_t byte;
    const uint8_t *p = *data;
    do {
        byte = *p++;
        result |= ((uintptr_t)(byte & 0x7F)) << shift;
        shift += 7;
    } while (byte & 0x80);
    *data = p;
    if ((byte & 0x40) && (shift < (sizeof(result) * 8)))
        result |= (~(uintptr_t)0) << shift;
    return (intptr_t)result;
}

/* Read encoded pointer */
static uintptr_t readEncodedPointer(const uint8_t **data, uint8_t encoding) {
    if (encoding == DW_EH_PE_omit)
        return 0;
    
    const uint8_t *p = *data;
    uintptr_t result = 0;
    
    /* First get the value */
    switch (encoding & 0x0F) {
    case DW_EH_PE_absptr:
        result = *(const uintptr_t *)p;
        p += sizeof(uintptr_t);
        break;
    case DW_EH_PE_uleb128:
        result = readULEB128(&p);
        break;
    case DW_EH_PE_udata4:
        result = *(const uint32_t *)p;
        p += 4;
        break;
    case DW_EH_PE_sdata4:
        result = (uintptr_t)(intptr_t)*(const int32_t *)p;
        p += 4;
        break;
    default:
        /* Not supported */
        return 0;
    }
    
    /* Then handle relative addressing */
    switch (encoding & 0x70) {
    case DW_EH_PE_absptr:
        /* Absolute, do nothing */
        break;
    case DW_EH_PE_pcrel:
        if (result)
            result += (uintptr_t)(*data);
        break;
    default:
        /* Not supported */
        break;
    }
    
    /* Handle indirection */
    if (result && (encoding & DW_EH_PE_indirect))
        result = *(uintptr_t *)result;
    
    *data = p;
    return result;
}

/* ========================================================================= */
/* Stack Accessors                                                           */
/* ========================================================================= */

static struct _Unwind_FunctionContext *
__Unwind_SjLj_GetTopOfFunctionStack(void) {
    return SjLjContextStack;
}

static void
__Unwind_SjLj_SetTopOfFunctionStack(struct _Unwind_FunctionContext *fc) {
    SjLjContextStack = fc;
}

/* ========================================================================= */
/* Public API - Register/Unregister                                          */
/* ========================================================================= */

void _Unwind_SjLj_Register(struct _Unwind_FunctionContext *fc) {
    fc->prev = __Unwind_SjLj_GetTopOfFunctionStack();
    __Unwind_SjLj_SetTopOfFunctionStack(fc);
}

void _Unwind_SjLj_Unregister(struct _Unwind_FunctionContext *fc) {
    __Unwind_SjLj_SetTopOfFunctionStack(fc->prev);
}

/*
 * sjlj_longjmp - Transfer control to the dispatch block
 *
 * This is implemented in assembly (sjlj_longjmp.S) to properly restore
 * FP and SP from the jbuf before jumping to the dispatch address.
 *
 * For SJLJ, the jbuf layout set by __builtin_setjmp is:
 *   jbuf[0] = frame pointer
 *   jbuf[1] = dispatch address (where to land)
 *   jbuf[2] = stack pointer
 */
extern void sjlj_longjmp(void **jbuf, int val) __attribute__((noreturn));

/* ========================================================================= */
/* Context Accessors                                                         */
/* ========================================================================= */

uintptr_t _Unwind_GetLanguageSpecificData(struct _Unwind_Context *context) {
    _Unwind_FunctionContext_t ufc = (_Unwind_FunctionContext_t)context;
    return ufc->lsda;
}

uintptr_t _Unwind_GetGR(struct _Unwind_Context *context, int index) {
    _Unwind_FunctionContext_t ufc = (_Unwind_FunctionContext_t)context;
    return ufc->resumeParameters[index];
}

void _Unwind_SetGR(struct _Unwind_Context *context, int index, uintptr_t value) {
    _Unwind_FunctionContext_t ufc = (_Unwind_FunctionContext_t)context;
    ufc->resumeParameters[index] = (uint32_t)value;
}

uintptr_t _Unwind_GetIP(struct _Unwind_Context *context) {
    _Unwind_FunctionContext_t ufc = (_Unwind_FunctionContext_t)context;
    /* Return call site index + 1 */
    return ufc->resumeLocation + 1;
}

void _Unwind_SetIP(struct _Unwind_Context *context, uintptr_t value) {
    _Unwind_FunctionContext_t ufc = (_Unwind_FunctionContext_t)context;
    ufc->resumeLocation = (uint32_t)(value - 1);
}

uintptr_t _Unwind_GetRegionStart(struct _Unwind_Context *context) {
    (void)context;
    return 0; /* Not needed for SJLJ */
}

uintptr_t _Unwind_GetCFA(struct _Unwind_Context *context) {
    if (context) {
        _Unwind_FunctionContext_t ufc = (_Unwind_FunctionContext_t)context;
        return (uintptr_t)ufc->jbuf[2]; /* SP from jump buffer */
    }
    return 0;
}

void _Unwind_DeleteException(struct _Unwind_Exception *exception_object) {
    if (exception_object->exception_cleanup)
        (*exception_object->exception_cleanup)(_URC_FOREIGN_EXCEPTION_CAUGHT,
                                               exception_object);
}

/* ========================================================================= */
/* Unwinding Implementation                                                  */
/* ========================================================================= */

/* Phase 1: Search for a handler */
static _Unwind_Reason_Code
unwind_phase1(struct _Unwind_Exception *exception_object) {
    _Unwind_FunctionContext_t c = __Unwind_SjLj_GetTopOfFunctionStack();
    
    /* Walk each frame looking for a handler */
    for (; c != NULL; c = c->prev) {
        /* If there's a personality routine, ask if it will handle this */
        if (c->personality != NULL) {
            _Unwind_Reason_Code result = (*c->personality)(
                1, _UA_SEARCH_PHASE, exception_object->exception_class,
                exception_object, (struct _Unwind_Context *)c);
            
            switch (result) {
            case _URC_HANDLER_FOUND:
                /* Found a catch or cleanup - remember this context */
                exception_object->private_2 = (uintptr_t)c;
                return _URC_NO_REASON;
                
            case _URC_CONTINUE_UNWIND:
                /* Keep searching */
                break;
                
            default:
                /* Error */
                return _URC_FATAL_PHASE1_ERROR;
            }
        }
    }
    
    /* No handler found */
    return _URC_END_OF_STACK;
}

/* Phase 2: Run cleanups and transfer to handler */
static _Unwind_Reason_Code
unwind_phase2(struct _Unwind_Exception *exception_object) {
    _Unwind_FunctionContext_t c = __Unwind_SjLj_GetTopOfFunctionStack();
    
    while (c != NULL) {
        /* If there's a personality routine, tell it we're unwinding */
        if (c->personality != NULL) {
            _Unwind_Action action = _UA_CLEANUP_PHASE;
            if ((uintptr_t)c == exception_object->private_2)
                action |= _UA_HANDLER_FRAME;
            
            _Unwind_Reason_Code result = (*c->personality)(
                1, action, exception_object->exception_class,
                exception_object, (struct _Unwind_Context *)c);
            
            switch (result) {
            case _URC_CONTINUE_UNWIND:
                /* Continue to next frame */
                break;
                
            case _URC_INSTALL_CONTEXT:
                /* Transfer control to landing pad via longjmp */
                __Unwind_SjLj_SetTopOfFunctionStack(c);
                sjlj_longjmp(c->jbuf, 1);
                /* Never returns */
                return _URC_FATAL_PHASE2_ERROR;
                
            default:
                return _URC_FATAL_PHASE2_ERROR;
            }
        }
        c = c->prev;
    }
    
    return _URC_FATAL_PHASE2_ERROR;
}

/* ========================================================================= */
/* Public API - Raise Exception                                              */
/* ========================================================================= */

_Unwind_Reason_Code
_Unwind_SjLj_RaiseException(struct _Unwind_Exception *exception_object) {
    /* Mark as non-forced unwind */
    exception_object->private_1 = 0;
    exception_object->private_2 = 0;
    
    /* Phase 1: Search for handler */
    _Unwind_Reason_Code phase1_result = unwind_phase1(exception_object);
    if (phase1_result != _URC_NO_REASON)
        return phase1_result;
    
    /* Phase 2: Run cleanups and transfer to handler */
    return unwind_phase2(exception_object);
}
/* Resume unwinding after a cleanup or rethrow */
void _Unwind_SjLj_Resume(struct _Unwind_Exception *exception_object)
    __attribute__((noreturn));
    
void _Unwind_SjLj_Resume(struct _Unwind_Exception *exception_object) {
    /* For rethrow, we need to skip the current frame (which caught the exception)
       and continue searching from the parent frame.
       
       First, re-run phase 1 to find a handler in outer frames, then run phase 2.
       This is similar to a fresh _Unwind_SjLj_RaiseException but we skip the 
       innermost frame since we're resuming after a catch. */
    
    _Unwind_FunctionContext_t c = __Unwind_SjLj_GetTopOfFunctionStack();
    
    /* Skip current frame - we already handled the exception there */
    if (c != NULL) {
        c = c->prev;
    }
    
    if (c == NULL) {
        /* No more frames - exception not handled */
        extern void abort(void) __attribute__((noreturn));
        abort();
    }
    
    /* Phase 1: Find a handler in remaining frames */
    _Unwind_FunctionContext_t saved_c = c;
    while (c != NULL) {
        if (c->personality != NULL) {
            _Unwind_Reason_Code result = (*c->personality)(
                1, _UA_SEARCH_PHASE, exception_object->exception_class,
                exception_object, (struct _Unwind_Context *)c);
            
            if (result == _URC_HANDLER_FOUND) {
                /* Remember which frame has the handler */
                exception_object->private_2 = (uintptr_t)c;
                break;
            }
        }
        c = c->prev;
    }
    
    if (c == NULL) {
        /* No handler found - terminate */
        extern void abort(void) __attribute__((noreturn));
        abort();
    }
    
    /* Phase 2: Run cleanups and install handler, starting from the first skipped frame */
    c = saved_c;
    while (c != NULL) {
        if (c->personality != NULL) {
            _Unwind_Action action = _UA_CLEANUP_PHASE;
            if ((uintptr_t)c == exception_object->private_2)
                action |= _UA_HANDLER_FRAME;
            
            _Unwind_Reason_Code result = (*c->personality)(
                1, action, exception_object->exception_class,
                exception_object, (struct _Unwind_Context *)c);
            
            if (result == _URC_INSTALL_CONTEXT) {
                /* Transfer control to landing pad */
                __Unwind_SjLj_SetTopOfFunctionStack(c);
                sjlj_longjmp(c->jbuf, 1);
                /* Never returns */
            }
        }
        c = c->prev;
    }
    
    /* If we get here, something went wrong */
    extern void abort(void) __attribute__((noreturn));
    abort();
}

/* For compatibility - may be called by some code */
_Unwind_Reason_Code
_Unwind_SjLj_Resume_or_Rethrow(struct _Unwind_Exception *exception_object) {
    if (exception_object->private_1 == 0) {
        /* Non-forced, rethrow */
        return _Unwind_SjLj_RaiseException(exception_object);
    }
    /* Forced unwind - resume */
    _Unwind_SjLj_Resume(exception_object);
    /* Never reaches here */
    return _URC_FATAL_PHASE2_ERROR;
}

/* _Unwind_Resume - called by cleanup landing pads to continue unwinding.
   This is the generic name that LLVM generates calls to. */
void _Unwind_Resume(struct _Unwind_Exception *exception_object) 
    __attribute__((noreturn));

void _Unwind_Resume(struct _Unwind_Exception *exception_object) {
    _Unwind_SjLj_Resume(exception_object);
}

/* ========================================================================= */
/* C++ Personality Function                                                  */
/* ========================================================================= */

/*
 * LSDA format for SJLJ:
 * - lpStartEncoding (1 byte)
 * - lpStart (if lpStartEncoding != DW_EH_PE_omit)
 * - ttypeEncoding (1 byte)
 * - classInfoOffset (ULEB128, if ttypeEncoding != DW_EH_PE_omit)
 * - callSiteEncoding (1 byte) - ignored for SJLJ
 * - callSiteTableLength (ULEB128)
 * - Call site table: entries of (landingPad ULEB128, actionEntry ULEB128)
 * - Action table
 * - Type table (grows backwards from classInfo)
 */

/* Forward declaration for type matching from cxxabi_typeinfo.c */
struct __class_type_info;
extern int __cxa_type_match(const struct __class_type_info *thrown_type,
                            const struct __class_type_info *catch_type,
                            void **adjustedPtr);

static int
can_catch(const void *catchType, const void *thrownType, void **adjustedPtr) {
    /* Use the proper RTTI-aware type matching */
    return __cxa_type_match(
        (const struct __class_type_info *)thrownType,
        (const struct __class_type_info *)catchType,
        adjustedPtr);
}

_Unwind_Reason_Code __gxx_personality_v0(
    int version,
    _Unwind_Action actions,
    uint64_t exceptionClass,
    struct _Unwind_Exception *exception_object,
    struct _Unwind_Context *context)
{
    if (version != 1)
        return _URC_FATAL_PHASE1_ERROR;
    
    /* Check if this is a C++ exception */
    int native_exception = ((exceptionClass & 0xFFFFFFFFFFFFFF00ULL) ==
                           (kOurExceptionClass & 0xFFFFFFFFFFFFFF00ULL));
    
    /* Get LSDA */
    const uint8_t *lsda = (const uint8_t *)_Unwind_GetLanguageSpecificData(context);
    if (lsda == NULL)
        return _URC_CONTINUE_UNWIND;
    
    /* Get current call site index (1-based) */
    uintptr_t ip = _Unwind_GetIP(context) - 1;
    
    /* ip == -1 means no action */
    if (ip == (uintptr_t)-1)
        return _URC_CONTINUE_UNWIND;
    
    /* ip == 0 is invalid */
    if (ip == 0) {
        extern void abort(void) __attribute__((noreturn));
        abort();
    }
    
    /* Parse LSDA header */
    uint8_t lpStartEncoding = *lsda++;
    if (lpStartEncoding != DW_EH_PE_omit)
        readEncodedPointer(&lsda, lpStartEncoding);
    
    const uint8_t *classInfo = NULL;
    uint8_t ttypeEncoding = *lsda++;
    if (ttypeEncoding != DW_EH_PE_omit) {
        uintptr_t classInfoOffset = readULEB128(&lsda);
        classInfo = lsda + classInfoOffset;
    }
    
    /* Skip call site encoding (not used for SJLJ) */
    lsda++; /* callSiteEncoding */
    
    /* Get call site table */
    uintptr_t callSiteTableLength = readULEB128(&lsda);
    const uint8_t *callSiteTableStart = lsda;
    const uint8_t *callSiteTableEnd = callSiteTableStart + callSiteTableLength;
    const uint8_t *actionTableStart = callSiteTableEnd;
    
    /* Search call site table for current ip */
    const uint8_t *callSitePtr = callSiteTableStart;
    uintptr_t landingPad = 0;
    uintptr_t actionEntry = 0;
    
    while (callSitePtr < callSiteTableEnd) {
        /* For SJLJ, each entry is: (landingPad ULEB128, actionEntry ULEB128) */
        landingPad = readULEB128(&callSitePtr);
        actionEntry = readULEB128(&callSitePtr);
        
        if (--ip == 0) {
            /* Found our call site */
            break;
        }
    }
    
    if (ip != 0) {
        /* Didn't find call site - this shouldn't happen */
        extern void abort(void) __attribute__((noreturn));
        abort();
    }
    

    
    /* landingPad is 0-based dispatch switch value + 1 */
    landingPad++;
    
    /* No action entry means just cleanup */
    if (actionEntry == 0) {
        if (actions & _UA_SEARCH_PHASE)
            return _URC_CONTINUE_UNWIND;
        /* Cleanup phase - install landing pad */
        /* Set exception object in data[0] and selector=0 in data[1] */
        _Unwind_SetGR(context, 0, (uintptr_t)exception_object);
        _Unwind_SetGR(context, 1, 0);  /* selector = 0 for cleanup */
        _Unwind_SetIP(context, landingPad);
        return _URC_INSTALL_CONTEXT;
    }
    
    /* Process action table */
    const uint8_t *action = actionTableStart + (actionEntry - 1);
    
    while (1) {
        intptr_t ttypeIndex = readSLEB128(&action);
        
        if (ttypeIndex > 0) {
            /* This is a catch handler */
            const void *catchType = NULL;
            
            if (classInfo && ttypeEncoding != DW_EH_PE_omit) {
                /* Get the type info for this catch */
                /* The type table is indexed backwards from classInfo */
                /* We need to use the ttype encoding to read the pointer */
                const uint8_t *typePtr = classInfo - ttypeIndex * 4; /* 4 bytes per entry for 32-bit */
                catchType = (const void *)readEncodedPointer(&typePtr, ttypeEncoding);
            }
            
            /* Get the thrown exception type */
            void *adjustedPtr = NULL;
            const void *thrownType = NULL;
            
            if (native_exception) {
                /* exception_object is _Unwind_Exception* pointing to unwindHeader */
                /* Navigate back to __cxa_exception using offsetof */
                struct __cxa_exception *exc_header = 
                    (struct __cxa_exception *)((char *)exception_object - 
                        __builtin_offsetof(struct __cxa_exception, unwindHeader));
                thrownType = exc_header->exceptionType;
                adjustedPtr = exc_header + 1; /* Thrown object follows header */
            }
            
            /* Check if this catch can handle the exception */
            if (can_catch(catchType, thrownType, &adjustedPtr)) {
                if (actions & _UA_SEARCH_PHASE) {
                    /* Phase 1: Remember we found a handler */
                    if (native_exception) {
                        struct __cxa_exception *exc_header =
                            (struct __cxa_exception *)((char *)exception_object - 
                                __builtin_offsetof(struct __cxa_exception, unwindHeader));
                        exc_header->handlerSwitchValue = (int)ttypeIndex;
                        exc_header->actionRecord = action;
                        exc_header->languageSpecificData = lsda;
                        exc_header->catchTemp = (void *)landingPad;
                        exc_header->adjustedPtr = adjustedPtr;
                    }
                    return _URC_HANDLER_FOUND;
                } else {
                    /* Phase 2: Install handler */
                    _Unwind_SetGR(context, 0, (uintptr_t)exception_object);
                    _Unwind_SetGR(context, 1, (uintptr_t)ttypeIndex);
                    _Unwind_SetIP(context, landingPad);
                    return _URC_INSTALL_CONTEXT;
                }
            }
        } else if (ttypeIndex == 0) {
            /* Cleanup handler - only run in phase 2 */
            if (actions & _UA_CLEANUP_PHASE) {
                _Unwind_SetGR(context, 0, (uintptr_t)exception_object);
                _Unwind_SetGR(context, 1, 0);
                _Unwind_SetIP(context, landingPad);
                return _URC_INSTALL_CONTEXT;
            }
        }
        /* ttypeIndex < 0 is exception spec - skip for now */
        
        /* Get next action offset */
        /* Note: The offset is self-relative from the START of the actionOffset field */
        /* per Itanium C++ ABI, so we save position before reading */
        const uint8_t *actionOffsetPos = action;
        intptr_t actionOffset = readSLEB128(&action);
        

        
        if (actionOffset == 0)
            break; /* End of action list */
        
        /* Apply offset relative to the start of the actionOffset field, not after it */
        action = actionOffsetPos + actionOffset;
    }
    
    /* No handler found */
    return _URC_CONTINUE_UNWIND;
}

/* SJLJ personality - calls the same implementation as v0 */
_Unwind_Reason_Code __gxx_personality_sj0(
    int version,
    _Unwind_Action actions,
    uint64_t exceptionClass,
    struct _Unwind_Exception *exception_object,
    struct _Unwind_Context *context)
{
    return __gxx_personality_v0(version, actions, exceptionClass,
                                exception_object, context);
}
