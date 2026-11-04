# ZKTeco ADMS Attendance (Push)

This module integrates ZKTeco biometric devices (e.g., SpeedFace-V5L) with Odoo's `hr_attendance` using the ADMS / iClock cloud-push protocol. 

## How it Works

1. **Push-Based Architecture**: Unlike traditional polling where Odoo periodically requests data from the device, this module makes the biometric device act as an HTTP client. The device proactively pushes attendance transactions (ATTLOG) and operation logs (OPERLOG) to Odoo.
2. **Immutable Audit Log**: Raw punches received from the device are securely stored in an immutable log (`zkteco.biometric.attendance.log`). 
3. **Attendance Policy Engine**: A configurable engine evaluates these raw punches and translates them into actual Check-In and Check-Out records in `hr.attendance`.
4. **Offline Resilience**: De-duplication mechanisms prevent duplicate entries if the device goes offline and replays logs when it reconnects.

## Where Can I Use This Module?

- Any Odoo environment utilizing the `hr_attendance` module for tracking employee time.
- Businesses utilizing modern ZKTeco biometric devices (such as the SpeedFace series) that support the **ADMS / Cloud Server Settings** feature.
- Multi-company setups where different devices belong to different branches or companies.

## How to Use This Module

### Step 1: Odoo Configuration
1. Install the `zkteco_adms_attendance` module.
2. Go to **Attendances > Configuration > Biometric Devices**.
3. Create a new device:
   - **Name**: Main Entrance SpeedFace
   - **Serial Number**: Enter the exact SN of the device (e.g., `CJQG20211119`).
   - **Timezone**: Set the timezone of the physical device location.
   - **Auth Token (Optional)**: A shared secret for secure communication.
4. Change the state of the device from **Draft** to **Confirmed**. The device must be "Confirmed" to be allowed to push data.

### Step 2: ZKTeco Device Configuration (ADMS)
1. On your physical ZKTeco device, go to **Menu > Comm. > Cloud Server Settings** (or ADMS).
2. Set the **Server Address** to your Odoo server's IP or Domain (e.g., `192.168.1.50`).
3. Set the **Server Port** to your Odoo port (e.g., `8069`).
4. Set the **Enable Domain Name** appropriately.
5. Once configured, the device will immediately ping Odoo.
6. Check Odoo: Your device state should automatically transition to **Online**, and the firmware version will be populated.

### Step 3: Map Employees
1. In Odoo, go to the Employee record.
2. Under the **HR Settings** tab, ensure the employee has a matching **Device ID / PIN** configured. This ID matches the User ID registered on the biometric device.

## Example Data

Here is an example flow of how data is processed:

**1. Biometric Device Configuration:**
- Name: `Front Desk Scanner`
- Serial Number: `CJQG2123490`
- State: `Online` (Connected)

**2. Employee Setup:**
- Employee: `Mitchell Admin`
- Biometric Device ID: `1001` (This is Mitchell's ID on the physical scanner)

**3. Employee Punches In:**
- *Physical Action*: Mitchell scans his face at 08:30 AM.
- *Raw Log Received*: The device pushes an ATTLOG to Odoo. A `biometric.attendance.log` is created: 
  - Device: `Front Desk Scanner`
  - PIN: `1001`
  - Timestamp: `2023-10-01 08:30:00`
  - Status: `Check-in`

**4. Policy Engine Execution:**
- The Attendance Policy Engine reads the raw log for PIN `1001`.
- It matches PIN `1001` to employee `Mitchell Admin`.
- It creates an `hr.attendance` record for Mitchell with a Check-In time of `08:30 AM`.
