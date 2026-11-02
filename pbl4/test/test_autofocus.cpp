#include "autofocus_control.h"
#include <assert.h>
#include <map>
#include <array>
#include <stdio.h>
struct Bus {
  uint32_t now=0;
  std::map<uint16_t,int> regs;
  std::map<int,std::array<int,4>> zones;
  int writeFault=-1, readFault=-1;
  bool firmwareRuns=true, ackClears=true, contrast=true;
  uint32_t focusDelay=0, focusAt=0;
  uint32_t millis() { return now; }
  void delay(unsigned ms) { now+=ms; }
  bool write(uint16_t reg,uint8_t value) {
    if (reg==writeFault) return false;
    regs[reg]=value;
    if (reg==0x3000 && value==0 && firmwareRuns) regs[0x3029]=0x70;
    if (reg==0x3022 && ackClears) {
      regs[0x3023]=0;
      if (value>=0x90 && value<=0x94) zones[value]={regs[0x3024],regs[0x3025],regs[0x3026],regs[0x3027]};
      if (value==0x03) {
        focusAt=now+focusDelay;
        regs[0x3029]=focusDelay ? 0 : (contrast ? 0x10:0x70);
      }
    }
    return true;
  }
  int read(uint16_t reg) {
    if (reg==0x3029 && focusDelay && int32_t(now-focusAt)>=0) regs[reg]=contrast ? 0x10:0x70;
    return reg==readFault ? -1:regs[reg];
  }
};
int main() {
  const uint8_t firmware[]={0x02,0x0f,0xd6};
  Bus bus; autofocus::Control<Bus> af(bus);
  assert(!af.continuous() && !af.single());
  assert(!af.begin(nullptr,3) && !af.ready());
  assert(af.begin(firmware,sizeof(firmware)) && af.ready());
  assert(bus.regs[0x8000]==2 && bus.regs[0x8002]==0xd6);
  assert(af.continuous() && bus.regs[0x3022]==4);
  assert(af.pause() && bus.regs[0x3022]==6);
  assert(af.zone() && bus.regs[0x3022]==0x80);
  assert(af.zone(25,30,true,false));
  assert(bus.regs[0x3022]==0x81 && bus.regs[0x3024]==60 && bus.regs[0x3025]==18);
  assert(af.zone(0,100,false,false));
  assert(bus.regs[0x3024]==8 && bus.regs[0x3025]==54);
  assert(!af.zone(101,0));
  assert(af.single() && af.status()==0x10);
  bus.focusDelay=150;
  const auto lensStart=bus.now;
  assert(af.single(500) && bus.now-lensStart>=150);
  bus.focusDelay=1000;
  assert(!af.single(100) && af.error()==autofocus::Error::Timeout);
  bus.focusDelay=0;
  bus.contrast=false;
  assert(!af.single() && af.error()==autofocus::Error::NoContrast && af.ready());
  bus.ackClears=false; const auto started=bus.now;
  assert(!af.single(50) && af.error()==autofocus::Error::Timeout);
  assert(bus.now-started==50);
  bus.ackClears=true; bus.writeFault=0x3022;
  assert(!af.continuous() && af.error()==autofocus::Error::Write);
  bus.writeFault=-1; bus.readFault=0x3023;
  assert(!af.single() && af.error()==autofocus::Error::Read);
  bus.readFault=-1; bus.firmwareRuns=false;
  bus.now=0xfffffff0u;
  assert(!af.begin(firmware,sizeof(firmware)) && !af.ready() && af.error()==autofocus::Error::Timeout);
  bus.firmwareRuns=true; bus.writeFault=0x8001;
  assert(!af.begin(firmware,sizeof(firmware)) && !af.ready() && af.error()==autofocus::Error::Write);
  af.reset(); assert(!af.ready());
  puts("PASS OV5640 autofocus: firmware load, continuous/single/pause, low contrast, I2C faults, timeout, timer rollover");
}
