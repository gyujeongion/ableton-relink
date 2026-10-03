# Run from the repo root:  vhs demo/demo.tape
Output demo/demo.gif
Set Shell "bash"
Set FontSize 15
Set Width 1150
Set Height 640
Set Padding 18
Set TypingSpeed 35ms
Set Theme "Dracula"

Hide
Type "source demo/env.sh"
Enter
Sleep 1s
Show

Type "ableton-relink scan 'Night Drive Project'"
Enter
Sleep 3s
Type "ableton-relink run 'Night Drive Project' --search library"
Enter
Sleep 4s
Type "ableton-relink scan 'Night Drive Project'"
Enter
Sleep 4s
