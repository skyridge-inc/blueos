FROM ubuntu:latest

 # Update and install sudo and curl
 RUN apt-get update && \
     apt-get install -y sudo curl && \
     apt-get clean && \
     rm -rf /var/lib/apt/lists/*

 # Create a non-root user with home directory
 RUN useradd -m -s /bin/bash developer

 # Add user to sudoers with no password required
 RUN echo "developer ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

 # Switch to the non-root user
 USER developer

 # Set working directory to user's home
 WORKDIR /home/developer

 # Default command
 CMD ["/bin/bash"]