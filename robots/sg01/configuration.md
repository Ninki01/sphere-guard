Auto run when restart

```
@reboot sleep 10 && /home/sguard/miniforge3/envs/robot-env/bin/python /home/sguard/sphere-guard/robots/sg01/src/test_file/robot_server.py >> /home/sguard/sphere-guard/robots/sg01/src/test_file/robot.log 2>&1
```


edit the configuration file:

```
nano /home/sguard/sphere-guard/robots/sg01/src/test_file/robot_server.py
```


### change the path 

Step 1: Open the editor
Run this command in your terminal:

Bash
```
crontab -e
```

If it asks you to choose an editor, press 1 for /bin/nano (it's the easiest).

Step 2: Update the file path
Scroll down to the bottom of the file using your arrow keys. Look for the @reboot line you want to change:

Plaintext
```
@reboot sleep 10 && /home/sguard/miniforge3/envs/robot-env/bin/python /home/sguard/sphere-guard/robots/sg01/src/test_file/robot_server.py >> /home/sguard/sphere-guard/robots/sg01/src/test_file/robot.log 2>&1
```
To run a different file: Delete /home/sguard/sphere-guard/robots/sg01/src/test_file/robot_server.py and replace it with the absolute path to your new script.

To change where the logs go: Change the path after the >> symbol (this is where errors and text outputs are saved if the script crashes).

Step 3: Save and Exit
Once you have modified the line:

Press Ctrl + O (Write Out) and hit Enter to save the changes.

Press Ctrl + X to exit the editor.