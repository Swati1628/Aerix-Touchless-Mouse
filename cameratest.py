import cv2

cap = cv2.VideoCapture(0, cv2.CAP_MSMF)

if not cap.isOpened():
    print("Camera could not be opened")
    exit()

print("Camera opened")

while True:
    ret, frame = cap.read()

    if not ret:
        print("Could not read frame")
        break

    # MIRROR THE CAMERA
    frame = cv2.flip(frame, 1)

    cv2.imshow("Camera Test - Right Hand", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()