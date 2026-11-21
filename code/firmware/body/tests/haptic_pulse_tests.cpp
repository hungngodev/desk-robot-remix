#include "HapticPulse.h"
#include <cassert>
#include <cstdint>
#include <iostream>
using desk_robot::HapticPulse;
int main(){
 HapticPulse h;
 assert(!h.request(10));
 h.configure(true);
 assert(h.request(100));
 assert(!h.request(101));
 assert(h.next(120,false)==HapticPulse::Action::None);
 assert(!h.active());
 assert(h.request(130));
 assert(h.next(180,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,180);
 assert(h.active());
 assert(!h.request(181));
 assert(h.next(270,false)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,true,270);
 assert(!h.active());
 assert(!h.request(500));
 assert(h.request(1680));
 assert(h.next(1931,true)==HapticPulse::Action::None);
 assert(h.request(1950));
 assert(h.next(1990,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,1990);
 assert(h.next(2080,false)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,false,2080);
 assert(!h.ready());
 assert(!h.request(4000));
 h.configure(true);
 assert(h.request(0xfffffffaU));
 assert(h.next(4U,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,4);
 assert(h.next(100,true)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,true,100);
 assert(!h.request(1499));
 assert(h.request(1504));
 h.fault();
 assert(h.next(1520,true)==HapticPulse::Action::None);
 std::cout<<"PASS haptic requests, cooldown, dock gating, fault, wrap\n";
}
