// Minimal <cxxabi.h> header for Subleq C++ runtime
// Declares __cxxabiv1 ABI types and __dynamic_cast

#ifndef __CXXABI_H
#define __CXXABI_H

// Compatibility version macro required by libc++
// Value > 1001 enables __cxa_uncaught_exceptions() (plural) API
#define _LIBCPPABI_VERSION 15000

#include <stddef.h>

namespace __cxxabiv1 {

// Base type_info class for types with no base classes  
class __class_type_info {
public:
    virtual ~__class_type_info();
    const char* __type_name;
};

// Type info for single non-virtual public inheritance
class __si_class_type_info : public __class_type_info {
public:
    const __class_type_info* __base_type;
};

// Base class info for VMI type info
struct __base_class_type_info {
    const __class_type_info* __base_type;
    long __offset_flags;
    
    enum __offset_flags_masks {
        __virtual_mask = 0x1,
        __public_mask = 0x2,
        __offset_shift = 8
    };
    
    bool __is_virtual() const { return __offset_flags & __virtual_mask; }
    bool __is_public() const { return __offset_flags & __public_mask; }
    ptrdiff_t __offset() const { return __offset_flags >> __offset_shift; }
};

// Type info for virtual or multiple inheritance
class __vmi_class_type_info : public __class_type_info {
public:
    unsigned int __flags;
    unsigned int __base_count;
    __base_class_type_info __base_info[1]; // Variable length array
    
    enum __flags_masks {
        __non_diamond_repeat_mask = 0x1,
        __diamond_shaped_mask = 0x2
    };
};

// Fundamental type info (int, char, etc.)
class __fundamental_type_info : public __class_type_info {
};

// Pointer type info
class __pointer_type_info : public __class_type_info {
public:
    unsigned int __flags;
    const __class_type_info* __pointee;
};

// Pointer to member type info
class __pointer_to_member_type_info : public __pointer_type_info {
public:
    const __class_type_info* __context;
};

} // namespace __cxxabiv1

namespace abi = __cxxabiv1;

namespace __cxxabiv1 {
extern "C" {

// Exception handling (required by libc++)
int __cxa_uncaught_exceptions();
bool __cxa_uncaught_exception();

// Exception pointer support (required by libc++ exception_pointer)
void __cxa_increment_exception_refcount(void* p);
void __cxa_decrement_exception_refcount(void* p);
void* __cxa_current_primary_exception();
void __cxa_rethrow_primary_exception(void* p);

} // extern "C"
} // namespace __cxxabiv1

extern "C" {

// Core dynamic_cast runtime function
// Returns adjusted pointer or nullptr on failure
void* __dynamic_cast(
    const void* src_ptr,                              // Pointer to source object
    const __cxxabiv1::__class_type_info* src_type,   // Static type of source
    const __cxxabiv1::__class_type_info* dst_type,   // Target type
    ptrdiff_t src2dst_offset);                        // Hint: known offset, or -1/-2/-3

} // extern "C"

#endif // __CXXABI_H
