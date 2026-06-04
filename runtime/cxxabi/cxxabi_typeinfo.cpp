/*
 * C++ RTTI Implementation for Subleq Linux
 * 
 * Implements __dynamic_cast and exception type matching.
 * 
 * Key insight: The compiler generates type_info objects with vtables that
 * only contain the destructor. We CANNOT add custom virtual functions
 * because those vtable slots won't exist in compiler-generated type_info.
 * 
 * Instead, we detect type_info subclass via the RTTI name from vptr[-1]
 * and use non-virtual helper functions for inheritance traversal.
 */

#include <stddef.h>

extern "C" {
extern void abort(void) __attribute__((noreturn));
extern int strcmp(const char *s1, const char *s2);
extern char *strstr(const char *haystack, const char *needle);
extern char *strcpy(char *dest, const char *src);
extern char *strcat(char *dest, const char *src);
extern size_t strlen(const char *s);
extern void *malloc(size_t size);
extern void free(void *ptr);
}

// Placement new operator for in-place construction
inline void* operator new(size_t, void* ptr) noexcept { return ptr; }

// ============================================================================
// Standard Exception Classes
// ============================================================================

namespace std {

// --- std::type_info ---
class type_info {
public:
    virtual ~type_info();

    bool operator==(const type_info& other) const;
    bool operator!=(const type_info& other) const;
    bool before(const type_info& other) const;
    const char* name() const;
    size_t hash_code() const;

protected:
    const char* __type_name;

    type_info(const type_info&) = delete;
    type_info& operator=(const type_info&) = delete;
};

type_info::~type_info() {}

bool type_info::operator==(const type_info& other) const {
    return __type_name == other.__type_name ||
           (strcmp(__type_name, other.__type_name) == 0);
}

bool type_info::operator!=(const type_info& other) const {
    return !operator==(other);
}

bool type_info::before(const type_info& other) const {
    return strcmp(__type_name, other.__type_name) < 0;
}

const char* type_info::name() const {
    return __type_name;
}

size_t type_info::hash_code() const {
    return reinterpret_cast<size_t>(__type_name);
}

// --- std::exception ---
class exception {
public:
    exception() noexcept;
    exception(const exception&) noexcept {}
    exception& operator=(const exception&) noexcept { return *this; }
    virtual ~exception() noexcept;
    virtual const char* what() const noexcept;
};

exception::exception() noexcept {}
exception::~exception() noexcept {}
const char* exception::what() const noexcept { return "std::exception"; }

// --- std::bad_exception ---
class bad_exception : public exception {
public:
    bad_exception() noexcept;
    virtual ~bad_exception() noexcept;
    virtual const char* what() const noexcept;
};

bad_exception::bad_exception() noexcept {}
bad_exception::~bad_exception() noexcept {}
const char* bad_exception::what() const noexcept { return "std::bad_exception"; }

// --- std::logic_error ---
class logic_error : public exception {
public:
    logic_error(const char* msg) : _msg(nullptr) {
        if (msg) {
            size_t len = strlen(msg);
            _msg = (char*)malloc(len + 1);
            if (_msg) strcpy(_msg, msg);
        }
    }
    logic_error(const logic_error& other) : exception(other), _msg(nullptr) {
        if (other._msg) {
            size_t len = strlen(other._msg);
            _msg = (char*)malloc(len + 1);
            if (_msg) strcpy(_msg, other._msg);
        }
    }
    virtual ~logic_error() noexcept;
    virtual const char* what() const noexcept;
private:
    char* _msg;
};

logic_error::~logic_error() noexcept { if (_msg) free(_msg); }
const char* logic_error::what() const noexcept {
    return _msg ? _msg : "std::logic_error";
}

// --- std::length_error ---
class length_error : public logic_error {
public:
    length_error(const char* msg) : logic_error(msg) {}
    length_error(const length_error& other) : logic_error(other) {}
    virtual ~length_error() noexcept;
};

length_error::~length_error() noexcept {}

// --- std::out_of_range ---
class out_of_range : public logic_error {
public:
    out_of_range(const char* msg) : logic_error(msg) {}
    out_of_range(const out_of_range& other) : logic_error(other) {}
    virtual ~out_of_range() noexcept;
};

out_of_range::~out_of_range() noexcept {}

// --- std::invalid_argument ---
class invalid_argument : public logic_error {
public:
    invalid_argument(const char* msg) : logic_error(msg) {}
    invalid_argument(const invalid_argument& other) : logic_error(other) {}
    virtual ~invalid_argument() noexcept;
};

invalid_argument::~invalid_argument() noexcept {}

// --- std::domain_error ---
class domain_error : public logic_error {
public:
    domain_error(const char* msg) : logic_error(msg) {}
    domain_error(const domain_error& other) : logic_error(other) {}
    virtual ~domain_error() noexcept;
};

domain_error::~domain_error() noexcept {}

// --- std::runtime_error ---
class runtime_error : public exception {
public:
    runtime_error(const char* msg) : _msg(nullptr) {
        if (msg) {
            size_t len = strlen(msg);
            _msg = (char*)malloc(len + 1);
            if (_msg) strcpy(_msg, msg);
        }
    }
    runtime_error(const runtime_error& other) : exception(other), _msg(nullptr) {
        if (other._msg) {
            size_t len = strlen(other._msg);
            _msg = (char*)malloc(len + 1);
            if (_msg) strcpy(_msg, other._msg);
        }
    }
    virtual ~runtime_error() noexcept;
    virtual const char* what() const noexcept;
private:
    char* _msg;
};

runtime_error::~runtime_error() noexcept { if (_msg) free(_msg); }
const char* runtime_error::what() const noexcept {
    return _msg ? _msg : "std::runtime_error";
}

// --- std::overflow_error ---
class overflow_error : public runtime_error {
public:
    overflow_error(const char* msg) : runtime_error(msg) {}
    overflow_error(const overflow_error& other) : runtime_error(other) {}
    virtual ~overflow_error() noexcept;
};

overflow_error::~overflow_error() noexcept {}

// --- std::underflow_error ---
class underflow_error : public runtime_error {
public:
    underflow_error(const char* msg) : runtime_error(msg) {}
    underflow_error(const underflow_error& other) : runtime_error(other) {}
    virtual ~underflow_error() noexcept;
};

underflow_error::~underflow_error() noexcept {}

// --- std::range_error ---
class range_error : public runtime_error {
public:
    range_error(const char* msg) : runtime_error(msg) {}
    range_error(const range_error& other) : runtime_error(other) {}
    virtual ~range_error() noexcept;
};

range_error::~range_error() noexcept {}

// --- std::bad_cast / std::bad_typeid ---
class bad_cast : public exception {
public:
    bad_cast() noexcept;
    virtual ~bad_cast() noexcept;
    virtual const char* what() const noexcept { return "std::bad_cast"; }
};

bad_cast::bad_cast() noexcept {}
bad_cast::~bad_cast() noexcept {}

class bad_typeid : public exception {
public:
    bad_typeid() noexcept;
    virtual ~bad_typeid() noexcept;
    virtual const char* what() const noexcept { return "std::bad_typeid"; }
};

bad_typeid::bad_typeid() noexcept {}
bad_typeid::~bad_typeid() noexcept {}

// --- std::bad_alloc ---
class bad_alloc : public exception {
public:
    bad_alloc() noexcept;
    virtual ~bad_alloc() noexcept;
    virtual const char* what() const noexcept { return "std::bad_alloc"; }
};

bad_alloc::bad_alloc() noexcept {}
bad_alloc::~bad_alloc() noexcept {}

// --- std::bad_array_new_length ---
class bad_array_new_length : public bad_alloc {
public:
    bad_array_new_length() noexcept;
    virtual ~bad_array_new_length() noexcept;
    virtual const char* what() const noexcept { return "std::bad_array_new_length"; }
};

bad_array_new_length::bad_array_new_length() noexcept {}
bad_array_new_length::~bad_array_new_length() noexcept {}

// --- new_handler support ---
typedef void (*new_handler)();
static new_handler __new_handler = nullptr;

new_handler set_new_handler(new_handler handler) noexcept {
    new_handler old = __new_handler;
    __new_handler = handler;
    return old;
}

new_handler get_new_handler() noexcept {
    return __new_handler;
}

// --- terminate_handler support ---
typedef void (*terminate_handler)();
static terminate_handler __terminate_handler = nullptr;

terminate_handler set_terminate(terminate_handler handler) noexcept {
    terminate_handler old = __terminate_handler;
    __terminate_handler = handler;
    return old;
}

terminate_handler get_terminate() noexcept {
    return __terminate_handler;
}

void terminate() noexcept {
    if (__terminate_handler) {
        __terminate_handler();
    }
    abort();
}

} // namespace std

// External declarations for exception throwing
extern "C" {
void* __cxa_allocate_exception(size_t thrown_size);
void __cxa_throw(void* thrown_object, void* tinfo, void (*dest)(void*)) __attribute__((noreturn));
}

// Get type_info for std::bad_cast
namespace __cxxabiv1 {
class __class_type_info;
}
extern const __cxxabiv1::__class_type_info _ZTISt8bad_cast;
extern const __cxxabiv1::__class_type_info _ZTISt10bad_typeid;

// Destructor wrapper for exception cleanup
static void bad_cast_destructor(void* obj) {
    static_cast<std::bad_cast*>(obj)->~bad_cast();
}

static void bad_typeid_destructor(void* obj) {
    static_cast<std::bad_typeid*>(obj)->~bad_typeid();
}

extern "C" {

// Throw std::bad_cast for failed dynamic_cast<T&>
void __cxa_bad_cast(void) __attribute__((noreturn));
void __cxa_bad_cast(void) {
    // Allocate exception object
    void* exception = __cxa_allocate_exception(sizeof(std::bad_cast));
    // Construct the exception object in-place
    new (exception) std::bad_cast();
    // Throw it
    __cxa_throw(exception, (void*)&_ZTISt8bad_cast, bad_cast_destructor);
}

// Throw std::bad_typeid for typeid on null pointer
void __cxa_bad_typeid(void) __attribute__((noreturn));
void __cxa_bad_typeid(void) {
    void* exception = __cxa_allocate_exception(sizeof(std::bad_typeid));
    new (exception) std::bad_typeid();
    __cxa_throw(exception, (void*)&_ZTISt10bad_typeid, bad_typeid_destructor);
}

} // extern "C"

namespace __cxxabiv1 {

// Path access flags for inheritance traversal
enum { unknown = 0, public_path, not_public_path };

/*
 * Type_info structure layouts (as generated by the compiler):
 *
 * __class_type_info:
 *   [vptr, __type_name]
 *
 * __si_class_type_info (single non-virtual public inheritance):
 *   [vptr, __type_name, __base_type]
 *
 * __vmi_class_type_info (virtual/multiple inheritance):
 *   [vptr, __type_name, __flags, __base_count, __base_info[]]
 *
 * __base_class_type_info (entry in __vmi):
 *   [__base_type, __offset_flags]
 */

// Forward declarations
class __class_type_info;
class __si_class_type_info;
class __vmi_class_type_info;
struct __base_class_type_info;

// Base class type info - for types with no base classes
class __class_type_info : public std::type_info {
public:
    virtual ~__class_type_info();
};

__class_type_info::~__class_type_info() {}

// Single inheritance type info
class __si_class_type_info : public __class_type_info {
public:
    const __class_type_info* __base_type;
    
    virtual ~__si_class_type_info();
};

__si_class_type_info::~__si_class_type_info() {}

// Base class info entry for VMI
struct __base_class_type_info {
    const __class_type_info* __base_type;
    long __offset_flags;
    
    enum { __virtual_mask = 0x1, __public_mask = 0x2, __offset_shift = 8 };
    
    bool is_virtual() const { return __offset_flags & __virtual_mask; }
    bool is_public() const { return __offset_flags & __public_mask; }
    ptrdiff_t offset() const { return __offset_flags >> __offset_shift; }
};

// Virtual/multiple inheritance type info
class __vmi_class_type_info : public __class_type_info {
public:
    unsigned int __flags;
    unsigned int __base_count;
    __base_class_type_info __base_info[1];  // Variable length
    
    virtual ~__vmi_class_type_info();
};

__vmi_class_type_info::~__vmi_class_type_info() {}

// Fundamental type info (int, char, etc.)
class __fundamental_type_info : public std::type_info {
public:
    virtual ~__fundamental_type_info();
};

__fundamental_type_info::~__fundamental_type_info() {}

// Pointer base type info
class __pbase_type_info : public std::type_info {
public:
    unsigned int __flags;
    const std::type_info* __pointee;
    
    virtual ~__pbase_type_info();
};

__pbase_type_info::~__pbase_type_info() {}

// Pointer type info
class __pointer_type_info : public __pbase_type_info {
public:
    virtual ~__pointer_type_info();
};

__pointer_type_info::~__pointer_type_info() {}

// Pointer-to-member type info
class __pointer_to_member_type_info : public __pbase_type_info {
public:
    const __class_type_info* __context;
    
    virtual ~__pointer_to_member_type_info();
};

__pointer_to_member_type_info::~__pointer_to_member_type_info() {}

// ============================================================================
// Runtime Type Detection via RTTI Names
// ============================================================================

/*
 * Get the RTTI name of a type_info object's own class.
 * This comes from vptr[-1], which points to the type_info's own type_info.
 */
static const char* get_typeinfo_class_name(const std::type_info* ti) {
    if (!ti) return nullptr;
    const void* const* vptr = *reinterpret_cast<const void* const* const*>(ti);
    if (!vptr) return nullptr;
    const std::type_info* ti_rtti = 
        reinterpret_cast<const std::type_info*>(vptr[-1]);
    if (!ti_rtti) return nullptr;
    return ti_rtti->name();
}

// Check if type_info is __si_class_type_info
static bool is_si_class(const std::type_info* ti) {
    const char* name = get_typeinfo_class_name(ti);
    if (!name) return false;
    return strstr(name, "si_class_type_info") != nullptr;
}

// Check if type_info is __vmi_class_type_info
static bool is_vmi_class(const std::type_info* ti) {
    const char* name = get_typeinfo_class_name(ti);
    if (!name) return false;
    return strstr(name, "vmi_class_type_info") != nullptr;
}

// ============================================================================
// Inheritance Traversal (Non-Virtual)
// ============================================================================

/*
 * Check if 'derived' inherits from 'base' via public inheritance.
 * Returns the adjusted pointer if found, nullptr otherwise.
 */
static const void* is_public_base_of(
    const __class_type_info* derived,
    const __class_type_info* base,
    const void* derived_ptr);

// Forward declaration for recursive call
static const void* check_base(
    const __class_type_info* check_type,
    const __class_type_info* target_base,
    const void* obj_ptr);

static const void* check_base(
    const __class_type_info* check_type,
    const __class_type_info* target_base,
    const void* obj_ptr)
{
    // Exact match?
    if (*check_type == *target_base) {
        return obj_ptr;
    }
    
    // Check for __si_class_type_info (single inheritance)
    if (is_si_class(check_type)) {
        const __si_class_type_info* si = 
            reinterpret_cast<const __si_class_type_info*>(check_type);
        // __si has base at offset 0, so pointer doesn't change
        return check_base(si->__base_type, target_base, obj_ptr);
    }
    
    // Check for __vmi_class_type_info (multiple/virtual inheritance)
    if (is_vmi_class(check_type)) {
        const __vmi_class_type_info* vmi = 
            reinterpret_cast<const __vmi_class_type_info*>(check_type);
        
        for (unsigned int i = 0; i < vmi->__base_count; i++) {
            const __base_class_type_info* bi = &vmi->__base_info[i];
            
            // Skip non-public bases
            if (!bi->is_public()) continue;
            
            // Compute offset to this base
            ptrdiff_t base_offset;
            if (bi->is_virtual()) {
                // Virtual base: read offset from vtable
                if (!obj_ptr) continue;  // Can't compute without object
                const void* const* vptr = 
                    *reinterpret_cast<const void* const* const*>(obj_ptr);
                base_offset = *reinterpret_cast<const ptrdiff_t*>(
                    reinterpret_cast<const char*>(vptr) + bi->offset());
            } else {
                base_offset = bi->offset();
            }
            
            const void* base_ptr = obj_ptr ? 
                static_cast<const char*>(obj_ptr) + base_offset : nullptr;
            
            const void* result = check_base(bi->__base_type, target_base, base_ptr);
            if (result) return result;
        }
    }
    
    // __class_type_info has no bases
    return nullptr;
}

static const void* is_public_base_of(
    const __class_type_info* derived,
    const __class_type_info* base,
    const void* derived_ptr)
{
    return check_base(derived, base, derived_ptr);
}

} // namespace __cxxabiv1

// ============================================================================
// C Interface for __dynamic_cast
// ============================================================================

using namespace __cxxabiv1;

// Get most-derived object info from vtable
static void get_most_derived(const void* ptr,
                             const void** md_ptr_out,
                             const __class_type_info** md_type_out) {
    if (!ptr) {
        *md_ptr_out = nullptr;
        *md_type_out = nullptr;
        return;
    }
    
    // vptr is first field of object
    const void* const* vptr = *reinterpret_cast<const void* const* const*>(ptr);
    
    // vptr[-2] is offset-to-top, vptr[-1] is RTTI pointer
    ptrdiff_t offset_to_top = reinterpret_cast<ptrdiff_t>(vptr[-2]);
    const __class_type_info* md_type = 
        reinterpret_cast<const __class_type_info*>(vptr[-1]);
    
    const void* md_ptr = static_cast<const char*>(ptr) + offset_to_top;
    
    *md_ptr_out = md_ptr;
    *md_type_out = md_type;
}

extern "C" void* __dynamic_cast(
    const void* src_ptr,
    const __class_type_info* src_type,
    const __class_type_info* dst_type,
    ptrdiff_t src2dst_offset)
{
    (void)src_type;
    (void)src2dst_offset;
    
    if (!src_ptr) return nullptr;
    
    // Get most-derived object
    const void* md_ptr;
    const __class_type_info* md_type;
    get_most_derived(src_ptr, &md_ptr, &md_type);
    
    if (!md_ptr || !md_type) return nullptr;
    
    // dynamic_cast<void*> returns most-derived object
    if (!dst_type) {
        return const_cast<void*>(md_ptr);
    }
    
    // Check if dst_type is the most-derived type
    if (*md_type == *dst_type) {
        return const_cast<void*>(md_ptr);
    }
    
    // Check if dst_type is a public base of most-derived
    const void* result = is_public_base_of(md_type, dst_type, md_ptr);
    if (result) {
        return const_cast<void*>(result);
    }
    
    return nullptr;
}

// ============================================================================
// Exception Type Matching
// ============================================================================

extern "C" int __cxa_type_match(
    const __class_type_info* thrown_type,
    const __class_type_info* catch_type,
    void** adjustedPtr)
{
    // catch(...) catches everything
    if (!catch_type) return 1;
    
    // Exact type match
    if (*thrown_type == *catch_type) return 1;
    
    // Check if thrown_type derives from catch_type
    void* ptr = adjustedPtr ? *adjustedPtr : nullptr;
    const void* result = is_public_base_of(thrown_type, catch_type, ptr);
    if (result) {
        if (adjustedPtr) *adjustedPtr = const_cast<void*>(result);
        return 1;
    }
    
    return 0;
}

// Note: std::type_info operators defined above as member functions
// (their out-of-line definitions provide the external symbols)
